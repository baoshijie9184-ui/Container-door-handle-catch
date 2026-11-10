package com.ruanzhu.doorhandle.module.model.service;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.JdbcTransactions;
import com.ruanzhu.doorhandle.framework.persistence.workflow.*;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** Upload state and immutable retention facts; no filesystem I/O and no physical file deletion. */
@Repository
public class ModelFilePersistence {
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final JdbcWorkflowStore workflows;
    public ModelFilePersistence(JdbcTemplate jdbc,ObjectMapper json) {
        this.jdbc=jdbc;
        this.json=json.copy().setSerializationInclusion(JsonInclude.Include.ALWAYS)
                .enable(DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES,DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);
        this.workflows=new JdbcWorkflowStore(jdbc,this.json,ModelFileProtocol.protocols());
    }
    public void validateSchema() {
        jdbc.queryForList("SELECT workflow_id,resource_id,model_file_storage_path,model_file_path_sha256,model_file_content_sha256,model_file_byte_size,model_file_model_id,status,revision FROM workflow_instance WHERE 1=0");
        jdbc.queryForList("SELECT event_id,resource_id,request_id,content_sha256,quantity,unit,outcome,revision,occurred_at,payload_json FROM audit_event WHERE 1=0");
    }
    public WorkflowRecord reserve(long actor,String fileId,String request,String path) {
        var row=claim(actor,fileId,request,path,ModelFileProtocol.requestDigest(actor,fileId,request,ModelFileProtocol.sha(path)));
        if(!"RESERVED".equals(row.status()))throw new WorkflowConflictException("模型文件请求已推进，不能重新写入文件");
        return row;
    }
    public Optional<WorkflowRecord> byRequest(long actor,String request){
        ModelFileProtocol.request(request);
        return workflows.findByRequest(WorkflowKind.MODEL_FILE_UPLOAD,JdbcWorkflowStore.ownerScope(actor),request);
    }
    public WorkflowRecord claim(long actor,String fileId,String request,String path,String intentDigest) {
        JdbcTransactions.requireActive(jdbc);
        if(intentDigest==null||!intentDigest.matches("[a-f0-9]{64}"))throw new IllegalArgumentException("模型上传请求摘要无效");
        var body=new ModelFileProtocol.UploadV1(path,ModelFileProtocol.sha(path),null,null,null,null,null);
        return workflows.create(new WorkflowDraft(ModelFileProtocol.UPLOAD_PREFIX+fileId,WorkflowKind.MODEL_FILE_UPLOAD,
                JdbcWorkflowStore.ownerScope(actor),request,intentDigest,
                actor,actor,null,"DETECTION_MODEL_FILE",fileId,null,null,null,"RESERVED",null,1,body));
    }
    public WorkflowRecord ready(long actor,ModelUploadFiles.Prepared file) {
        var before=owned(actor,file,"RESERVED");var body=payload(before);
        return workflows.transition(before,"FILE_READY",body.ready(file.sha256(),file.size()),null,null,null);
    }
    public WorkflowRecord registered(long actor,ModelUploadFiles.Prepared file,int modelId) {
        var before=owned(actor,file,"FILE_READY");var body=payload(before);
        if(!Objects.equals(body.contentSha256(),file.sha256())||!Objects.equals(body.byteSize(),file.size()))
            throw new IllegalStateException("模型文件登记证据不一致");
        return workflows.transition(before,"REGISTERED",body.registered(modelId),null,null,null);
    }
    private WorkflowRecord owned(long actor,ModelUploadFiles.Prepared file,String state) {
        JdbcTransactions.requireActive(jdbc);ModelFileProtocol.identity(file.fileId());ModelFileProtocol.request(file.requestId());
        var row=workflows.findLocked(WorkflowKind.MODEL_FILE_UPLOAD,ModelFileProtocol.UPLOAD_PREFIX+file.fileId())
                .orElseThrow(()->new IllegalStateException("模型文件登记不存在"));
        var body=payload(row);
        if(actor!=file.actorUserId()||row.ownerUserId()!=actor||!Objects.equals(row.actorUserId(),actor)
                ||!row.requestId().equals(file.requestId())||!state.equals(row.status())||!body.storagePath().equals(file.path().toString()))
            throw new IllegalStateException("模型上传身份或状态已变化，保留文件待核对");
        return row;
    }
    public Optional<WorkflowRecord> registeredForUpdate(int modelId,String path) {
        JdbcTransactions.requireActive(jdbc);
        var ids=jdbc.queryForList("""
                SELECT workflow_id FROM workflow_instance WHERE kind='MODEL_FILE_UPLOAD'
                  AND model_file_model_id=? AND status='REGISTERED' AND BINARY model_file_storage_path=BINARY ? FOR UPDATE
                """,String.class,modelId,path);
        if(ids.size()>1)throw new IllegalStateException("模型文件登记不唯一");
        return ids.isEmpty()?Optional.empty():workflows.findLocked(WorkflowKind.MODEL_FILE_UPLOAD,ids.get(0));
    }
    public void retained(WorkflowRecord before){workflows.transition(before,"RETAINED",payload(before),null,null,null);}
    public ModelFileProtocol.UploadV1 payload(WorkflowRecord row){return workflows.payload(row,ModelFileProtocol.UploadV1.class);}
    public void retain(String retentionId,int modelId,long actor,String request,String path,WorkflowRecord source) {
        JdbcTransactions.requireActive(jdbc);ModelFileProtocol.request(request);
        if(actor<=0)throw new IllegalArgumentException("模型文件操作人无效");
        LocalDateTime now=workflows.now();
        var facts=source==null?null:payload(source);
        if(source!=null&&(!"REGISTERED".equals(source.status())||!Objects.equals(facts.modelId(),modelId)||!facts.storagePath().equals(path)))
            throw new IllegalStateException("模型文件保留引用不一致");
        var body=new ModelFileProtocol.RetentionV1(retentionId,source==null?null:source.resourceId(),path,
                ModelFileProtocol.sha(path),now.toString(),null,null);
        String encoded;
        try{encoded=json.writeValueAsString(body);}catch(JsonProcessingException failure){throw new IllegalArgumentException("模型保留事实无法编码",failure);}
        // Deliberately no model FK and no request uniqueness: evidence outlives model deletion.
        jdbc.update("""
                INSERT INTO audit_event(event_id,kind,owner_user_id,actor_user_id,resource_type,resource_id,
                  request_id,action,revision,content_sha256,quantity,unit,outcome,occurred_at,payload_version,payload_json)
                VALUES(?,'MODEL_FILE_RETENTION',?,?,'DETECTION_MODEL',?,?,'RETAIN',0,?,?,?,?,?,1,?)
                """,ModelFileProtocol.RETENTION_PREFIX+retentionId,actor,actor,Integer.toString(modelId),request,
                facts==null?null:facts.contentSha256(),facts==null?null:facts.byteSize(),facts==null?null:"BYTES",
                facts==null?"RETAINED_LEGACY":"RETAINED",now,encoded);
    }
    public List<ModelFileJournal.UploadView> uploads(String request,int size) {
        String filter=request==null?"":" AND request_id=?";Object[] args=request==null?new Object[]{size}:new Object[]{request,size};
        return jdbc.query("""
                SELECT resource_id,actor_user_id,request_id,model_file_model_id,model_file_content_sha256,
                  model_file_byte_size,status,revision,updated_at FROM workflow_instance WHERE kind='MODEL_FILE_UPLOAD'
                """+filter+" ORDER BY created_at DESC,resource_id DESC LIMIT ?",(row,index)->new ModelFileJournal.UploadView(
                row.getString("resource_id"),row.getLong("actor_user_id"),row.getString("request_id"),(Integer)row.getObject("model_file_model_id"),
                row.getString("model_file_content_sha256"),(Long)row.getObject("model_file_byte_size"),row.getString("status"),row.getLong("revision"),
                businessTime(row.getObject("updated_at",LocalDateTime.class))),args);
    }
    public List<ModelFileJournal.RetentionView> retained(String request,int size) {
        String filter=request==null?"":" AND request_id=?";Object[] args=request==null?new Object[]{size}:new Object[]{request,size};
        return jdbc.query("""
                SELECT event_id,resource_id,actor_user_id,request_id,content_sha256,quantity,outcome,revision,payload_version,payload_json
                FROM audit_event WHERE kind='MODEL_FILE_RETENTION'
                """+filter+" ORDER BY occurred_at DESC,event_id DESC LIMIT ?",(row,index)->{
            if(row.getInt("payload_version")!=1)throw new IllegalStateException("不支持的模型保留事实版本");
            ModelFileProtocol.RetentionV1 body;
            try{body=json.readValue(row.getString("payload_json"),ModelFileProtocol.RetentionV1.class);}
            catch(JsonProcessingException invalid){throw new IllegalStateException("模型保留事实无法读取",invalid);}
            if(!row.getString("event_id").equals(ModelFileProtocol.RETENTION_PREFIX+body.retentionId()))throw new IllegalStateException("模型保留身份不一致");
            return new ModelFileJournal.RetentionView(body.retentionId(),Integer.parseInt(row.getString("resource_id")),row.getLong("actor_user_id"),
                    row.getString("request_id"),body.fileId(),row.getString("content_sha256"),(Long)row.getObject("quantity"),row.getString("outcome"),
                    row.getLong("revision"),businessTime(LocalDateTime.parse(body.updatedAtUtc())));
        },args);
    }
    private static LocalDateTime businessTime(LocalDateTime utc){return utc.atOffset(ZoneOffset.UTC).withOffsetSameInstant(ZoneOffset.ofHours(8)).toLocalDateTime();}
}
