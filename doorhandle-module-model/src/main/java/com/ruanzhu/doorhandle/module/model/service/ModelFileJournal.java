package com.ruanzhu.doorhandle.module.model.service;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import jakarta.annotation.PostConstruct;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.UUID;
import java.util.List;
import java.time.LocalDateTime;

/** Model-owned file intentions. No filesystem mutation is performed inside a SQL transaction. */
@Service
@ConditionalOnProperty(prefix="model.file-journal", name="enabled", havingValue="true")
public class ModelFileJournal {
    public record UploadView(String fileId,long actorUserId,String requestId,Integer modelId,String sha256,
                             Long bytes,String state,long revision,LocalDateTime updatedAt) {}
    public record RetentionView(String retentionId,int modelId,long actorUserId,String requestId,String fileId,
                                String sha256,Long bytes,String state,long revision,LocalDateTime updatedAt) {}
    public record View(boolean enabled,List<UploadView> uploads,List<RetentionView> retained) {}
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final OperationsAuditApi audit;
    private final ModelMutationIdentity identity;
    public ModelFileJournal(JdbcTemplate jdbc, PlatformTransactionManager manager,
                            OperationsAuditApi audit, ModelMutationIdentity identity) {
        this.jdbc=jdbc; this.tx=new TransactionTemplate(manager); this.tx.setTimeout(10);
        this.audit=audit; this.identity=identity;
    }
    @PostConstruct public void requireSchema() {
        jdbc.queryForList("SELECT file_id,state,revision FROM detection_model_file_journal WHERE 1=0");
        jdbc.queryForList("SELECT retention_id,state FROM detection_model_file_retention WHERE 1=0");
    }
    /** Explicit DTOs: never expose filesystem paths, file names, model bodies or a delete command. */
    public View list(String request,int size) {
        identity.supervisor();
        if(size<1 || size>100) throw new IllegalArgumentException("查询数量无效");
        if(request!=null && !request.matches("[A-Za-z0-9_-]{1,128}")) throw new IllegalArgumentException("请求编号无效");
        String where=request==null?"":" WHERE request_id=?";
        Object[] parameters=request==null?new Object[]{size}:new Object[]{request,size};
        var uploads=jdbc.query("SELECT file_id,actor_user_id,request_id,model_id,content_sha256,byte_size,state,revision,updated_at FROM detection_model_file_journal"+where+" ORDER BY created_at DESC,file_id DESC LIMIT ?",
                (row,index)->new UploadView(row.getString("file_id"),row.getLong("actor_user_id"),row.getString("request_id"),(Integer)row.getObject("model_id"),row.getString("content_sha256"),(Long)row.getObject("byte_size"),row.getString("state"),row.getLong("revision"),row.getTimestamp("updated_at").toLocalDateTime()),parameters);
        var retained=jdbc.query("SELECT retention_id,model_id,actor_user_id,request_id,file_id,content_sha256,byte_size,state,revision,updated_at FROM detection_model_file_retention"+where+" ORDER BY created_at DESC,retention_id DESC LIMIT ?",
                (row,index)->new RetentionView(row.getString("retention_id"),row.getInt("model_id"),row.getLong("actor_user_id"),row.getString("request_id"),row.getString("file_id"),row.getString("content_sha256"),(Long)row.getObject("byte_size"),row.getString("state"),row.getLong("revision"),row.getTimestamp("updated_at").toLocalDateTime()),parameters);
        return new View(true,uploads,retained);
    }
    public void reserve(String fileId, String requestId, String path) {
        outsideTransaction();
        var actor=identity.supervisor();
        tx.executeWithoutResult(status -> {
            jdbc.update("INSERT INTO detection_model_file_journal(file_id,actor_user_id,request_id,storage_path,path_sha256,state) VALUES(?,?,?,?,?,'RESERVED')",
                    fileId,actor.userId(),requestId,path,pathDigest(path));
            append(actor,"FILE_RESERVED",fileId,requestId,0);
        });
    }
    public void ready(ModelUploadFiles.Prepared file) {
        outsideTransaction();
        var actor=identity.supervisor();
        tx.executeWithoutResult(status -> {
            int changed=jdbc.update("UPDATE detection_model_file_journal SET state='FILE_READY',content_sha256=?,byte_size=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP(6) WHERE file_id=? AND actor_user_id=? AND request_id=? AND state='RESERVED' AND storage_path=?",
                    file.sha256(),file.size(),file.fileId(),actor.userId(),file.requestId(),file.path().toString());
            if(changed!=1) throw new IllegalStateException("模型上传状态已变化，保留文件待核对");
            append(actor,"FILE_READY",file.fileId(),file.requestId(),1);
        });
    }
    /** Invoked by the registry in the same transaction as the model row and mandatory audit. */
    public void registered(ModelUploadFiles.Prepared file, int modelId) {
        insideTransaction();
        var actor=identity.supervisor();
        int changed=jdbc.update("UPDATE detection_model_file_journal SET state='REGISTERED',model_id=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP(6) WHERE file_id=? AND actor_user_id=? AND request_id=? AND state='FILE_READY' AND storage_path=? AND content_sha256=? AND byte_size=?",
                modelId,file.fileId(),actor.userId(),file.requestId(),file.path().toString(),file.sha256(),file.size());
        if(changed!=1) throw new IllegalStateException("模型文件登记证据不一致");
        append(actor,"FILE_REGISTERED",file.fileId(),file.requestId(),2);
    }
    /** Retention, NOT a claim of physical deletion. Unknown/legacy files are never guessed away. */
    public void retain(ModelInfo model) {
        insideTransaction();
        var actor=identity.supervisor();
        var path=model.getModelPath();
        if(path==null || path.length()>2048) throw new IllegalStateException("模型文件位置无法登记，未删除模型");
        var managed=jdbc.queryForList("SELECT file_id,content_sha256,byte_size,revision FROM detection_model_file_journal WHERE model_id=? AND state='REGISTERED' AND storage_path=? FOR UPDATE",model.getModelId(),path);
        if(managed.size()>1) throw new IllegalStateException("模型文件登记不唯一");
        String retentionId=UUID.randomUUID().toString();
        String request=identity.requestId();
        var source=managed.isEmpty()?null:managed.get(0);
        jdbc.update("INSERT INTO detection_model_file_retention(retention_id,model_id,actor_user_id,request_id,file_id,storage_path,path_sha256,content_sha256,byte_size,state) VALUES(?,?,?,?,?,?,?,?,?,?)",
                retentionId,model.getModelId(),actor.userId(),request,source==null?null:source.get("file_id"),path,pathDigest(path),source==null?null:source.get("content_sha256"),source==null?null:source.get("byte_size"),source==null?"RETAINED_LEGACY":"RETAINED");
        if(source!=null) {
            int changed=jdbc.update("UPDATE detection_model_file_journal SET state='RETAINED',revision=revision+1,updated_at=CURRENT_TIMESTAMP(6) WHERE file_id=? AND state='REGISTERED' AND revision=?",source.get("file_id"),source.get("revision"));
            if(changed!=1) throw new IllegalStateException("模型文件登记已变化");
        }
        append(actor,"FILE_RETAINED",retentionId,request,0);
    }
    private void append(AgentActor actor,String action,String resource,String request,long version) {
        audit.append(new OperationsAuditApi.Event(actor,"ENTERPRISE","DETECTION_MODEL_FILE",action,resource,request,"APPLIED",version));
    }
    public static String pathDigest(String path) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(path.getBytes(StandardCharsets.UTF_8))); }
        catch(java.security.NoSuchAlgorithmException failure) { throw new IllegalStateException(failure); }
    }
    private static void outsideTransaction() {
        if(TransactionSynchronizationManager.isActualTransactionActive()) throw new IllegalStateException("模型文件写入不得占用业务事务");
    }
    private static void insideTransaction() {
        if(!TransactionSynchronizationManager.isActualTransactionActive()) throw new IllegalStateException("模型文件登记缺少业务事务");
    }
}
