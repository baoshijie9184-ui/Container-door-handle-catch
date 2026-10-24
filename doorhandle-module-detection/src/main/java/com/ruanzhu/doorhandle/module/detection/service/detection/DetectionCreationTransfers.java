package com.ruanzhu.doorhandle.module.detection.service.detection;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.infra.service.OssStorageService;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.*;
import org.springframework.transaction.support.TransactionTemplate;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** A target manifest is durable before any upload; a STARTED marker never authorizes another PUT. */
public final class DetectionCreationTransfers {
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;private final ObjectMapper json;
    private final OssStorageService oss;private final OperationsAuditApi audit;
    private record Target(int index,String file,String key,String sha256,long bytes,String contentType){}
    public record Manifest(String bucket,String prefix,List<String> keys){}
    public DetectionCreationTransfers(JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper json,OssStorageService oss,OperationsAuditApi audit){this.jdbc=jdbc;this.tx=new TransactionTemplate(manager);tx.setTimeout(10);this.json=json;this.oss=oss;this.audit=audit;}
    public void schema(){jdbc.queryForList("SELECT revision,bucket_name,source_prefix,manifest_sha256 FROM detection_creation_job WHERE 1=0");jdbc.queryForList("SELECT command_id,upload_token,state FROM detection_creation_object WHERE 1=0");}
    /** Caller owns the creation job transaction. PREPARING legacy commands may be initialized before first transfer. */
    public void prepare(AgentActor actor,String command,String task,String request,DetectionCreationApi.Preview preview){
        if(!org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive()||!oss.isConfigured())throw new IllegalStateException("批准传输清单需要就绪的存储及事务");
        String bucket=oss.getBucketName(),prefix=oss.normalizeBasePrefix()+"/agent-approved/"+actor.userId()+"/"+task+"/Original/";
        var targets=targets(prefix,preview);String fingerprint=hash(write(List.of(bucket,prefix,targets)));
        if(jdbc.update("UPDATE detection_creation_job SET bucket_name=?,source_prefix=?,manifest_sha256=? WHERE command_id=? AND actor_user_id=? AND status='PREPARING' AND manifest_sha256 IS NULL",bucket,prefix,fingerprint,command,actor.userId())!=1)throw new IllegalStateException("传输清单不能被替换");
        for(var target:targets)jdbc.update("INSERT INTO detection_creation_object(command_id,image_index,file_id,object_key,content_sha256,byte_length,content_type,state) VALUES(?,?,?,?,?,?,?,'PLANNED')",command,target.index(),target.file(),target.key(),target.sha256(),target.bytes(),target.contentType());
        audit.append(new OperationsAuditApi.Event(actor,"ENTERPRISE","DETECTION","CREATE_TRANSFER_MANIFEST",task,request,"PREPARED",0L));
    }
    public Manifest manifest(Map<String,Object> job,DetectionCreationApi.Preview preview){
        String bucket=(String)job.get("bucket_name"),prefix=(String)job.get("source_prefix");if(bucket==null||prefix==null||!bucket.equals(oss.getBucketName()))throw new IllegalStateException("原传输位置无法核对");
        var expected=targets(prefix,preview);if(!hash(write(List.of(bucket,prefix,expected))).equals(job.get("manifest_sha256")))throw new IllegalStateException("传输清单摘要无法核对");
        var rows=jdbc.queryForList("SELECT * FROM detection_creation_object WHERE command_id=? ORDER BY image_index",job.get("command_id"));if(rows.size()!=expected.size())throw new IllegalStateException("传输清单不完整");
        for(int i=0;i<rows.size();i++){var row=rows.get(i);var target=expected.get(i);if(((Number)row.get("image_index")).intValue()!=target.index()||!target.file().equals(row.get("file_id"))||!target.key().equals(row.get("object_key"))||!target.sha256().equals(row.get("content_sha256"))||((Number)row.get("byte_length")).longValue()!=target.bytes()||!target.contentType().equals(row.get("content_type")))throw new IllegalStateException("传输目标已变化");}
        return new Manifest(bucket,prefix,expected.stream().map(Target::key).toList());
    }
    public void upload(Map<String,Object> job,AgentActor actor,WorkspaceDetectionImagesApi.Image file,String key,byte[] bytes){
        String token=UUID.randomUUID().toString();tx.executeWithoutResult(status->{
            var current=jdbc.queryForMap("SELECT status,owner_token,(lease_until>CURRENT_TIMESTAMP(6)) AS live FROM detection_creation_job WHERE id=? FOR UPDATE",job.get("id"));
            if(!"UPLOADING".equals(current.get("status"))||!Objects.equals(job.get("owner_token"),current.get("owner_token"))||!flag(current.get("live")))throw new IllegalStateException("原传输执行权已失效");
            if(bytes.length!=file.bytes()||!hash(bytes).equals(file.sha256()))throw new IllegalStateException("批准图片内容已变化");
            if(jdbc.update("UPDATE detection_creation_object SET state='UPLOADING',upload_token=?,updated_at=CURRENT_TIMESTAMP(6) WHERE command_id=? AND file_id=? AND object_key=? AND state='PLANNED'",token,job.get("command_id"),file.fileId(),key)!=1)throw new IllegalStateException("该图片已发起传输 只允许核对原结果");
            jdbc.update("UPDATE detection_creation_job SET revision=revision+1 WHERE id=?",job.get("id"));
            audit.append(new OperationsAuditApi.Event(actor,"ENTERPRISE","DETECTION","CREATE_OBJECT_UPLOAD_STARTED",job.get("task_id")+":"+file.fileId(),(String)job.get("request_id"),"STARTED",revision(job)));
        });
        var receipt=oss.putApprovedObject(key,new java.io.ByteArrayInputStream(bytes),bytes.length,file.contentType(),(String)job.get("command_id"),file.fileId(),file.sha256());
        tx.executeWithoutResult(status->{
            jdbc.queryForMap("SELECT id FROM detection_creation_job WHERE id=? FOR UPDATE",job.get("id"));
            if(jdbc.update("UPDATE detection_creation_object SET state='STORED',etag=?,object_version=?,oss_request_id=?,updated_at=CURRENT_TIMESTAMP(6) WHERE command_id=? AND file_id=? AND upload_token=? AND state='UPLOADING'",receipt.etag(),receipt.versionId(),receipt.requestId(),job.get("command_id"),file.fileId(),token)!=1)throw new IllegalStateException("上传回执归属无法核对");
            jdbc.update("UPDATE detection_creation_job SET revision=revision+1 WHERE id=?",job.get("id"));
            audit.append(new OperationsAuditApi.Event(actor,"ENTERPRISE","DETECTION","CREATE_OBJECT_UPLOAD_ACK",job.get("task_id")+":"+file.fileId(),(String)job.get("request_id"),"ACKNOWLEDGED",revision(job)));
        });
    }
    public void assertStored(String command,int count){Long stored=jdbc.queryForObject("SELECT COUNT(*) FROM detection_creation_object WHERE command_id=? AND state='STORED'",Long.class,command);if(stored==null||stored!=count)throw new IllegalStateException("原图片传输回执尚未齐全");}
    private Long revision(Map<String,Object> job){return jdbc.queryForObject("SELECT revision FROM detection_creation_job WHERE id=?",Long.class,job.get("id"));}
    private List<Target> targets(String prefix,DetectionCreationApi.Preview preview){var values=new ArrayList<Target>();int index=0;for(var file:preview.images()){
        if(!file.fileId().matches("[a-f0-9-]{36}")||!file.sha256().matches("[a-f0-9]{64}")||!Set.of("image/jpeg","image/png").contains(file.contentType()))throw new IllegalArgumentException("传输图片身份无效");
        String key=prefix+file.fileId()+"-"+file.sha256()+(file.contentType().equals("image/png")?".png":".jpg");if(key.length()>1024)throw new IllegalArgumentException("传输目标超出限制");values.add(new Target(index++,file.fileId(),key,file.sha256(),file.bytes(),file.contentType()));
    }return List.copyOf(values);}
    private String write(Object value){try{return json.writeValueAsString(value);}catch(Exception error){throw new IllegalStateException("传输清单不可编码");}}
    private static boolean flag(Object value){return value instanceof Boolean b?b:value instanceof Number n&&n.intValue()!=0;}
    private static String hash(String value){return hash(value.getBytes(StandardCharsets.UTF_8));}
    private static String hash(byte[] bytes){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));}catch(java.security.NoSuchAlgorithmException error){throw new IllegalStateException(error);}}
}
