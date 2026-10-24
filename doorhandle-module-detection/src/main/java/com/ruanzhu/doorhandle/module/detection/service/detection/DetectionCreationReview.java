package com.ruanzhu.doorhandle.module.detection.service.detection;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.infra.service.OssStorageService;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** Detection-owned reconciliation: CHECK is read-only, FINALIZE and ABANDON are explicit owner decisions. */
final class DetectionCreationReview {
    interface Access {
        DetectionCreationApi.Preview validate(AgentActor actor,Map<String,Object> job);
        void validateImage(AgentActor actor,DetectionCreationApi.Preview preview,WorkspaceDetectionImagesApi.Image image);
        void publish(AgentActor actor,Map<String,Object> job,DetectionCreationApi.Preview preview);
    }
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;private final ObjectMapper json;
    private final OssStorageService oss;private final OperationsAuditApi audit;private final DetectionCreationTransfers transfers;private final Access access;
    DetectionCreationReview(JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper json,OssStorageService oss,
                            OperationsAuditApi audit,DetectionCreationTransfers transfers,Access access){
        this.jdbc=jdbc;tx=new TransactionTemplate(manager);tx.setTimeout(10);this.json=json;this.oss=oss;this.audit=audit;this.transfers=transfers;this.access=access;
    }
    void schema(){jdbc.queryForList("SELECT check_id,expected_revision,evidence_sha256,completed_revision FROM detection_creation_review WHERE 1=0");}
    List<DetectionCreationApi.TransferReview> list(AgentActor actor,String session){
        return jdbc.queryForList("SELECT * FROM detection_creation_job j WHERE actor_user_id=? AND session_id=? AND (status='NEEDS_REVIEW' OR EXISTS (SELECT 1 FROM detection_creation_review r WHERE r.command_id=j.command_id)) ORDER BY (status='NEEDS_REVIEW') DESC,id DESC LIMIT 20",actor.userId(),session).stream().map(this::view).toList();
    }
    DetectionCreationApi.TransferReview command(AgentActor actor,String session,String command,DetectionCreationApi.ReviewCommand input){
        if(input==null||input.revision()<0||input.requestId()==null||!input.requestId().matches("[A-Za-z0-9_-]{1,128}")||!Set.of("CHECK","FINALIZE","ABANDON").contains(input.action()==null?"":input.action()))throw new IllegalArgumentException("核对请求无效");
        if(input.checkId()!=null&&!input.checkId().matches("[a-f0-9-]{36}"))throw new IllegalArgumentException("核对记录编号无效");
        if(!"FINALIZE".equals(input.action())&&input.checkId()!=null)throw new IllegalArgumentException("此操作不接受其他核对记录");
        return tx.execute(status->{
            jdbc.queryForObject("SELECT user_id FROM detection_creation_owner WHERE user_id=? FOR UPDATE",Long.class,actor.userId());
            var job=owned(actor,session,command,true);var old=jdbc.queryForList("SELECT * FROM detection_creation_review WHERE actor_user_id=? AND request_id=?",actor.userId(),input.requestId());
            if(!old.isEmpty()){var prior=old.get(0);if(!command.equals(prior.get("command_id"))||!input.action().equals(prior.get("action"))||input.revision()!=number(prior,"expected_revision")||!Objects.equals(input.checkId(),prior.get("source_check_id")))throw conflict("请求编号已用于其他核对操作");return view(job);}
            if(input.revision()!=number(job,"revision"))throw conflict("创建命令版本已变化 请刷新");
            if(!"NEEDS_REVIEW".equals(job.get("status")))throw conflict("仅待核对的创建命令可以处置");
            String id=UUID.randomUUID().toString(),action=input.action(),result;
            if("ABANDON".equals(action)){
                // No source access is needed to stop one's own command. Unknown objects remain reserved and are not deleted.
                jdbc.update("UPDATE detection_creation_job SET status='CANCELLED',reason_code='USER_ABANDONED',owner_token=NULL,revision=revision+1,updated_at=CURRENT_TIMESTAMP(6) WHERE id=?",job.get("id"));
                jdbc.update("UPDATE detection_creation_review SET status='CANCELLED',reason_code='USER_ABANDONED',updated_at=CURRENT_TIMESTAMP(6) WHERE command_id=? AND status IN ('QUEUED','RUNNING')",command);result="CANCELLED";
            }else{
                var preview=access.validate(actor,job);transfers.manifest(job,preview);
                if("CHECK".equals(action)){
                    Long active=jdbc.queryForObject("SELECT COUNT(*) FROM detection_creation_review WHERE command_id=? AND status IN ('QUEUED','RUNNING')",Long.class,command);
                    if(active!=null&&active>0)throw conflict("已有核对进行中 请刷新原结果");
                    Long checks=jdbc.queryForObject("SELECT COUNT(*) FROM detection_creation_review WHERE command_id=? AND action='CHECK'",Long.class,command);if(checks!=null&&checks>=64)throw conflict("此命令核对次数已达上限 请保留证据后人工处理");
                    jdbc.update("UPDATE detection_creation_job SET revision=revision+1,updated_at=CURRENT_TIMESTAMP(6) WHERE id=?",job.get("id"));result="QUEUED";
                }else{
                    if(input.checkId()==null)throw conflict("请先完成只读核对");
                    var checks=jdbc.queryForList("SELECT *, (updated_at>DATE_SUB(CURRENT_TIMESTAMP(6),INTERVAL 5 MINUTE)) AS fresh FROM detection_creation_review WHERE command_id=? AND check_id=? AND action='CHECK' FOR UPDATE",command,input.checkId());
                    if(checks.isEmpty()||!validEvidence(job,checks.get(0),preview.images().size()))throw conflict("核对证据不完整、过期或命令已变化 请重新核对");
                    access.publish(actor,job,preview);result="COMPLETED";
                }
            }
            jdbc.update("INSERT INTO detection_creation_review(check_id,command_id,actor_user_id,request_id,expected_revision,action,source_check_id,status) VALUES(?,?,?,?,?,?,?,?)",id,command,actor.userId(),input.requestId(),input.revision(),action,input.checkId(),result);
            append(actor,job,input.requestId(),"CREATE_TRANSFER_"+action,result);
            return view(owned(actor,session,command,false));
        });
    }
    /** A previously RUNNING check is never replayed. A user may issue another explicitly read-only CHECK. */
    void poll(){
        for(var expired:jdbc.queryForList("SELECT command_id,check_id FROM detection_creation_review WHERE status='RUNNING' AND lease_until<CURRENT_TIMESTAMP(6) ORDER BY id LIMIT 8"))tx.executeWithoutResult(status->{
            var job=jdbc.queryForMap("SELECT * FROM detection_creation_job WHERE command_id=? FOR UPDATE",expired.get("command_id"));
            if(jdbc.update("UPDATE detection_creation_review SET status='UNCONFIRMED',reason_code='CHECK_INTERRUPTED',updated_at=CURRENT_TIMESTAMP(6) WHERE check_id=? AND status='RUNNING' AND lease_until<CURRENT_TIMESTAMP(6)",expired.get("check_id"))==1){
                jdbc.update("UPDATE detection_creation_job SET revision=revision+1 WHERE id=?",job.get("id"));append(originalActor(job),job,(String)expired.get("check_id"),"CREATE_TRANSFER_CHECK_INTERRUPTED","UNCONFIRMED");
            }
        });
        var candidates=jdbc.queryForList("SELECT command_id,check_id FROM detection_creation_review WHERE status='QUEUED' AND action='CHECK' ORDER BY id LIMIT 1");if(candidates.isEmpty())return;
        var candidate=candidates.get(0);String token=UUID.randomUUID().toString();
        var claimed=tx.execute(status->{
            var job=jdbc.queryForMap("SELECT * FROM detection_creation_job WHERE command_id=? FOR UPDATE",candidate.get("command_id"));
            if(!"NEEDS_REVIEW".equals(job.get("status"))){jdbc.update("UPDATE detection_creation_review SET status='CANCELLED',reason_code='COMMAND_TERMINATED',updated_at=CURRENT_TIMESTAMP(6) WHERE check_id=? AND status='QUEUED'",candidate.get("check_id"));return null;}
            if(jdbc.update("UPDATE detection_creation_review SET status='RUNNING',worker_token=?,lease_until=DATE_ADD(CURRENT_TIMESTAMP(6),INTERVAL 15 MINUTE),updated_at=CURRENT_TIMESTAMP(6) WHERE check_id=? AND status='QUEUED'",token,candidate.get("check_id"))!=1)return null;
            append(originalActor(job),job,(String)candidate.get("check_id"),"CREATE_TRANSFER_CHECK_STARTED","RUNNING");return job;
        });if(claimed==null)return;
        String check=(String)candidate.get("check_id");try{inspect(claimed,check,token);}catch(RuntimeException failure){finish(claimed,check,token,null,"CHECK_UNCONFIRMED");}
    }
    private void inspect(Map<String,Object> job,String check,String token){
        var actor=originalActor(job);var preview=access.validate(actor,job);transfers.manifest(job,preview);
        var objects=jdbc.queryForList("SELECT * FROM detection_creation_object WHERE command_id=? ORDER BY image_index",job.get("command_id"));var evidence=new ArrayList<Map<String,Object>>();
        int index=0;for(var item:objects){
            active(job,check,token);access.validateImage(actor,preview,preview.images().get(index++));
            var row=new LinkedHashMap<String,Object>();row.put("fileId",item.get("file_id"));String outcome="UNISSUED";
            if(item.get("upload_token")!=null&&Set.of("UPLOADING","STORED").contains(item.get("state"))){
                var remote=oss.inspectApprovedObject((String)item.get("object_key"),number(item,"byte_length"));
                boolean matches="READ".equals(remote.status())&&remote.bytes()==number(item,"byte_length")&&Objects.equals(remote.sha256(),item.get("content_sha256"))&&Objects.equals(remote.declaredSha256(),item.get("content_sha256"))&&Objects.equals(remote.contentType(),item.get("content_type"))&&Objects.equals(remote.commandId(),job.get("command_id"))&&Objects.equals(remote.fileId(),item.get("file_id"));
                outcome=matches?"VERIFIED":"MISSING".equals(remote.status())?"MISSING":"MISMATCH";
                row.put("sha256",remote.sha256());row.put("bytes",remote.bytes());row.put("etag",bounded(remote.etag(),128));row.put("version",bounded(remote.versionId(),1024));row.put("requestId",bounded(remote.requestId(),128));
            }
            row.put("status",outcome);evidence.add(row);int verified=(int)evidence.stream().filter(value->"VERIFIED".equals(value.get("status"))).count();
            tx.executeWithoutResult(status->{lockActive(job,check,token);String body=write(evidence);jdbc.update("UPDATE detection_creation_review SET checked_count=?,verified_count=?,evidence_json=?,evidence_sha256=?,lease_until=DATE_ADD(CURRENT_TIMESTAMP(6),INTERVAL 15 MINUTE) WHERE check_id=?",evidence.size(),verified,body,hash(body),check);
                append(actor,job,check,"CREATE_TRANSFER_OBJECT_CHECKED",(String)row.get("status"));});
        }
        finish(job,check,token,evidence,null);
    }
    private void finish(Map<String,Object> job,String check,String token,List<Map<String,Object>> evidence,String failure){
        tx.executeWithoutResult(status->{
            var rows=jdbc.queryForList("SELECT * FROM detection_creation_job WHERE id=? FOR UPDATE",job.get("id"));if(rows.isEmpty()||!"NEEDS_REVIEW".equals(rows.get(0).get("status")))return;
            var pending=jdbc.queryForList("SELECT * FROM detection_creation_review WHERE check_id=? AND status='RUNNING' AND worker_token=? AND lease_until>CURRENT_TIMESTAMP(6) FOR UPDATE",check,token);if(pending.isEmpty())return;
            var current=rows.get(0);if(failure==null){var preview=access.validate(originalActor(job),current);transfers.manifest(current,preview);}
            int count=evidence==null?((Number)pending.get(0).get("checked_count")).intValue():evidence.size(),verified=evidence==null?((Number)pending.get(0).get("verified_count")).intValue():(int)evidence.stream().filter(value->"VERIFIED".equals(value.get("status"))).count();
            String result=failure!=null?"UNCONFIRMED":verified==count&&count>0?"VERIFIED":"INCOMPLETE",body=evidence==null?(String)pending.get(0).get("evidence_json"):write(evidence);
            jdbc.update("UPDATE detection_creation_job SET revision=revision+1,updated_at=CURRENT_TIMESTAMP(6) WHERE id=?",job.get("id"));
            long revision=jdbc.queryForObject("SELECT revision FROM detection_creation_job WHERE id=?",Long.class,job.get("id"));
            jdbc.update("UPDATE detection_creation_review SET status=?,checked_count=?,verified_count=?,evidence_json=?,evidence_sha256=?,completed_revision=?,reason_code=?,updated_at=CURRENT_TIMESTAMP(6) WHERE check_id=?",result,count,verified,body,body==null?null:hash(body),revision,failure,check);
            append(originalActor(job),current,check,"CREATE_TRANSFER_CHECK_FINISHED",result);
        });
    }
    private boolean validEvidence(Map<String,Object> job,Map<String,Object> check,int count){
        if(!"VERIFIED".equals(check.get("status"))||!flag(check.get("fresh"))||check.get("completed_revision")==null||number(check,"completed_revision")!=number(job,"revision")||number(check,"checked_count")!=count||number(check,"verified_count")!=count||!(check.get("evidence_json") instanceof String body)||!hash(body).equals(check.get("evidence_sha256")))return false;
        try{var parsed=json.readTree(body);if(parsed==null||!parsed.isArray()||parsed.size()!=count)return false;var targets=jdbc.queryForList("SELECT file_id,content_sha256,byte_length FROM detection_creation_object WHERE command_id=? ORDER BY image_index",job.get("command_id"));if(targets.size()!=count)return false;
            for(int i=0;i<count;i++){var value=parsed.get(i);var target=targets.get(i);if(!"VERIFIED".equals(value.path("status").asText())||!target.get("file_id").equals(value.path("fileId").asText())||!target.get("content_sha256").equals(value.path("sha256").asText())||number(target,"byte_length")!=value.path("bytes").asLong(-1))return false;}return true;
        }catch(com.fasterxml.jackson.core.JsonProcessingException invalid){return false;}
    }
    private DetectionCreationApi.TransferReview view(Map<String,Object> job){
        var checks=jdbc.queryForList("SELECT *, (updated_at>DATE_SUB(CURRENT_TIMESTAMP(6),INTERVAL 5 MINUTE)) AS fresh FROM detection_creation_review WHERE command_id=? AND action='CHECK' ORDER BY id DESC LIMIT 1",job.get("command_id"));var check=checks.isEmpty()?null:checks.get(0);
        int total=jdbc.queryForObject("SELECT COUNT(*) FROM detection_creation_object WHERE command_id=?",Integer.class,job.get("command_id")),stored=jdbc.queryForObject("SELECT COUNT(*) FROM detection_creation_object WHERE command_id=? AND state='STORED'",Integer.class,job.get("command_id"));
        boolean manifest=job.get("manifest_sha256")!=null;
        return new DetectionCreationApi.TransferReview((String)job.get("command_id"),(String)job.get("task_id"),(String)job.get("status"),number(job,"revision"),total,stored,manifest,check==null?null:(String)check.get("check_id"),check==null?null:(String)check.get("status"),check==null?0:((Number)check.get("checked_count")).intValue(),check==null?0:((Number)check.get("verified_count")).intValue(),"NEEDS_REVIEW".equals(job.get("status"))&&manifest&&check!=null&&validEvidence(job,check,total),(String)job.get("reason_code"),check==null?null:check.get("updated_at").toString());
    }
    private Map<String,Object> owned(AgentActor actor,String session,String command,boolean lock){var rows=jdbc.queryForList("SELECT * FROM detection_creation_job WHERE actor_user_id=? AND session_id=? AND command_id=?"+(lock?" FOR UPDATE":""),actor.userId(),session,command);if(rows.isEmpty())throw new SecurityException("创建命令不存在或无权限");return rows.get(0);}
    private void active(Map<String,Object> job,String check,String token){Long count=jdbc.queryForObject("SELECT COUNT(*) FROM detection_creation_review r JOIN detection_creation_job j ON j.command_id=r.command_id WHERE j.id=? AND j.status='NEEDS_REVIEW' AND r.check_id=? AND r.worker_token=? AND r.status='RUNNING' AND r.lease_until>CURRENT_TIMESTAMP(6)",Long.class,job.get("id"),check,token);if(count==null||count!=1)throw conflict("核对执行权已失效");}
    private void lockActive(Map<String,Object> job,String check,String token){jdbc.queryForMap("SELECT id FROM detection_creation_job WHERE id=? FOR UPDATE",job.get("id"));active(job,check,token);}
    private void append(AgentActor actor,Map<String,Object> job,String request,String action,String result){audit.append(new OperationsAuditApi.Event(actor,"ENTERPRISE","DETECTION",action,(String)job.get("task_id"),request,result,jdbc.queryForObject("SELECT revision FROM detection_creation_job WHERE id=?",Long.class,job.get("id"))));}
    private static AgentActor originalActor(Map<String,Object> job){return new AgentActor(number(job,"actor_user_id"),(String)job.get("actor_username"),AgentActor.Role.valueOf((String)job.get("actor_role")));}
    private static long number(Map<String,Object> value,String key){return ((Number)value.get(key)).longValue();}
    private static boolean flag(Object value){return value instanceof Boolean b?b:value instanceof Number n&&n.intValue()!=0;}
    private static String bounded(String value,int max){if(value!=null&&(value.length()>max||value.chars().anyMatch(Character::isISOControl)))throw conflict("远端回执格式不可核对");return value;}
    private String write(Object value){try{return json.writeValueAsString(value);}catch(com.fasterxml.jackson.core.JsonProcessingException error){throw conflict("核对证据不可保存");}}
    private static String hash(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(java.security.NoSuchAlgorithmException error){throw new IllegalStateException(error);}}
    private static IllegalStateException conflict(String text){return new IllegalStateException(text);}
}
