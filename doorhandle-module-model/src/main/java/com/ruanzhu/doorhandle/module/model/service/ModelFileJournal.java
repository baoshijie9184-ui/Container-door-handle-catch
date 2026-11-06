package com.ruanzhu.doorhandle.module.model.service;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import jakarta.annotation.PostConstruct;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.transaction.support.TransactionSynchronizationManager;
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
    private final ModelFilePersistence files;
    private final TransactionTemplate tx;
    private final OperationsAuditApi audit;
    private final ModelMutationIdentity identity;
    public ModelFileJournal(ModelFilePersistence files, PlatformTransactionManager manager,
                            OperationsAuditApi audit, ModelMutationIdentity identity) {
        this.files=files; this.tx=new TransactionTemplate(manager); this.tx.setTimeout(10);
        this.audit=audit; this.identity=identity;
    }
    @PostConstruct public void requireSchema() {files.validateSchema();}
    /** Explicit DTOs: never expose filesystem paths, file names, model bodies or a delete command. */
    public View list(String request,int size) {
        identity.supervisor();
        if(size<1 || size>100) throw new IllegalArgumentException("查询数量无效");
        if(request!=null && !request.matches("[A-Za-z0-9_-]{1,128}")) throw new IllegalArgumentException("请求编号无效");
        return new View(true,files.uploads(request,size),files.retained(request,size));
    }

    public void reserve(String fileId, String requestId, String path) {
        outsideTransaction();
        var actor=identity.supervisor();
        tx.executeWithoutResult(status -> {
            var row=files.reserve(actor.userId(),fileId,requestId,path);
            append(actor,"FILE_RESERVED",fileId,requestId,row.revision());
        });
    }
    public void ready(ModelUploadFiles.Prepared file) {
        outsideTransaction();
        var actor=identity.supervisor();
        tx.executeWithoutResult(status -> {
            var row=files.ready(actor.userId(),file);
            append(actor,"FILE_READY",file.fileId(),file.requestId(),row.revision());
        });
    }
    /** Invoked by the registry in the same transaction as the model row and mandatory audit. */
    public void registered(ModelUploadFiles.Prepared file, int modelId) {
        insideTransaction();
        var actor=identity.supervisor();
        var row=files.registered(actor.userId(),file,modelId);
        append(actor,"FILE_REGISTERED",file.fileId(),file.requestId(),row.revision());
    }

    /** Retention, NOT a claim of physical deletion. Unknown/legacy files are never guessed away. */
    public void retain(ModelInfo model) {
        insideTransaction();
        var actor=identity.supervisor();
        var path=model.getModelPath();
        if(path==null || path.length()>2048) throw new IllegalStateException("模型文件位置无法登记，未删除模型");
        var source=files.registeredForUpdate(model.getModelId(),path).orElse(null);
        String retentionId=UUID.randomUUID().toString();
        String request=identity.requestId();
        files.retain(retentionId,model.getModelId(),actor.userId(),request,path,source);
        if(source!=null)files.retained(source);
        append(actor,"FILE_RETAINED",retentionId,request,0);
    }
    private void append(AgentActor actor,String action,String resource,String request,long version) {
        audit.append(new OperationsAuditApi.Event(actor,"ENTERPRISE","DETECTION_MODEL_FILE",action,resource,request,"APPLIED",version));
    }
    public static String pathDigest(String path) {return ModelFileProtocol.sha(path);}
    private static void outsideTransaction() {
        if(TransactionSynchronizationManager.isActualTransactionActive()) throw new IllegalStateException("模型文件写入不得占用业务事务");
    }
    private static void insideTransaction() {
        if(!TransactionSynchronizationManager.isActualTransactionActive()) throw new IllegalStateException("模型文件登记缺少业务事务");
    }
}
