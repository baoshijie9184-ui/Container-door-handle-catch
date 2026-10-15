package com.ruanzhu.doorhandle.module.detection.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity;
import com.ruanzhu.doorhandle.module.detection.dto.report.QualityReportDtos.*;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.repository.QualityReportRepository;
import com.ruanzhu.doorhandle.module.detection.repository.QualityReportRepository.Row;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.time.temporal.ChronoUnit;
import java.util.*;

/** 私人草稿、冻结提交及独立人工审批；不修改任务推理结果、复核或放行状态。 */
@Service
@Transactional(isolation=Isolation.READ_COMMITTED,rollbackFor=Exception.class)
public class QualityReportService {
    private final QualityReportRepository reports;
    private final DetectionTaskMapper tasks;
    private final BusinessUserDirectory users;
    private final DetectionTaskAccessPolicy policy;
    private final ObjectMapper json;
    private final ObjectMapper canonicalJson;
    public QualityReportService(QualityReportRepository reports,DetectionTaskMapper tasks,BusinessUserDirectory users,
            DetectionTaskAccessPolicy policy,ObjectMapper json) {
        this.reports=reports;this.tasks=tasks;this.users=users;this.policy=policy;this.json=json;
        this.canonicalJson=json.copy().configure(com.fasterxml.jackson.databind.SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS,true)
                .configure(com.fasterxml.jackson.databind.MapperFeature.SORT_PROPERTIES_ALPHABETICALLY,true);
    }
    public Map<String,Object> list(Identity actor,int page,int size,String status,String keyword) {
        actor=current(actor);
        if(page<1||page>10000||size<1||size>100||(keyword!=null&&keyword.length()>128))fail(400,"查询参数不正确");
        if(status!=null&&!status.isBlank()&&!Set.of("DRAFT","SUBMITTED","APPROVED","REJECTED","WITHDRAWN").contains(status))fail(400,"报告状态不正确");
        var params=new HashMap<String,Object>();params.put("owner",actor.userId());params.put("username",actor.username());
        String where="(r.owner_user_id=:owner"+(actor.supervisor()?" OR r.status<>'DRAFT'":"")+")";
        if(!actor.supervisor())where+=" AND (t.created_by=:username OR t.assignee=:username)";
        if(status!=null&&!status.isBlank()){where+=" AND r.status=:status";params.put("status",status);}
        if(keyword!=null&&!keyword.isBlank()){where+=" AND (r.task_id LIKE :keyword OR r.title LIKE :keyword)";params.put("keyword","%"+keyword.trim()+"%");}
        var rows=reports.list(where,params,page,size);
        return Map.of("records",rows.stream().map(this::view).toList(),"total",reports.count(where,params),"page",page,"size",size);
    }
    public View get(Identity actor,String id) { actor=current(actor);return view(authorized(actor,id,false)); }
    public List<EventDelivery> events(Identity actor,String id) {
        actor=current(actor);authorized(actor,id,false);
        return reports.jdbc().query("SELECT e.event_id,e.event_type,e.delivery_status,e.attempts,e.next_attempt_at,e.delivered_at,e.last_error_code,r.consumed_at FROM detection_report_outbox e LEFT JOIN detection_report_event_receipt r ON r.event_id=e.event_id WHERE e.report_id=? ORDER BY e.created_at,e.event_id LIMIT 100",
                (r,n)->new EventDelivery(r.getString("event_id"),r.getString("event_type"),r.getString("delivery_status"),r.getInt("attempts"),r.getObject("next_attempt_at",LocalDateTime.class),r.getObject("delivered_at",LocalDateTime.class),r.getString("last_error_code"),r.getObject("consumed_at",LocalDateTime.class)),id);
    }
    public List<EventDelivery> retryEvent(Identity actor,String id,String eventId,RetryEvent request) {
        actor=current(actor);supervisor(actor);var row=authorized(actor,id,true);
        if(eventId==null||!eventId.matches("[a-f0-9-]{36}")||request==null||request.expectedAttempts()==null||request.expectedAttempts()<0||!request.confirmed())fail(400,"请核对事件并明确确认重试");
        String digest=commandDigest("EVENT_RETRY",id+":"+eventId,request);
        if(repeat(actor,request.requestId(),digest)!=null)return events(actor,id);
        if(reports.jdbc().update("UPDATE detection_report_outbox SET delivery_status='RETRY',next_attempt_at=?,last_error_code=NULL WHERE report_id=? AND event_id=? AND delivery_status IN ('FAILED','RETRY') AND attempts=?",now(),id,eventId,request.expectedAttempts())!=1)
            fail(409,"事件已变化或正在发送，请刷新后重试");
        writeAudit(actor,row,"EVENT_RETRY",row.status(),"人工确认重新投递报告事件");
        reports.jdbc().update("INSERT INTO detection_report_command(actor_user_id,request_id,command_sha256,report_id,response_json,created_at) VALUES(?,?,?,?,?,?)",actor.userId(),request.requestId(),digest,id,encode(view(row)),now());
        return events(actor,id);
    }
    public List<Audit> audit(Identity actor,String id) {
        actor=current(actor);authorized(actor,id,false);
        return reports.jdbc().query("SELECT a.*,o.run_id,o.call_id,o.tool_name FROM detection_report_audit a LEFT JOIN detection_report_agent_origin o ON o.report_id=a.report_id AND o.report_version=a.report_version AND o.actor_user_id=a.actor_user_id AND a.action IN ('CREATE','EDIT') WHERE a.report_id=? ORDER BY a.id DESC LIMIT 100",
                (r,n)->new Audit(r.getLong("id"),r.getString("actor_username"),r.getString("action"),r.getString("before_status"),
                        r.getString("after_status"),r.getInt("report_version"),r.getString("reason"),r.getString("snapshot_sha256"),r.getObject("created_at",LocalDateTime.class),r.getString("run_id"),r.getString("call_id"),r.getString("tool_name")),id);
    }
    public View create(Identity actor,Create request) {
        actor=current(actor);validateText(request.title(),request.narrative());
        String digest=commandDigest("CREATE",request.taskId(),request);
        var repeated=repeat(actor,request.requestId(),digest);if(repeated!=null)return repeated;
        var task=task(actor,request.taskId(),true);eligible(task);
        repeated=repeat(actor,request.requestId(),digest);if(repeated!=null)return repeated;
        return newDraft(actor,task,null,request.title().trim(),request.narrative(),request.requestId(),digest);
    }
    public View edit(Identity actor,String id,Edit request) {
        actor=current(actor);validateText(request.title(),request.narrative());
        String digest=commandDigest("EDIT",id,request);
        var row=authorized(actor,id,true);owner(actor,row);
        var repeated=repeat(actor,request.requestId(),digest);if(repeated!=null)return repeated;
        version(row,request.expectedVersion());state(row,"DRAFT");
        var task=task(actor,row.taskId(),true);eligible(task);
        reports.jdbc().update("UPDATE detection_quality_report SET title=?,narrative=?,source_json=?,source_sha256=?,version=version+1,updated_at=? WHERE report_id=?",
                request.title().trim(),request.narrative(),encode(facts(task)),sourceDigest(task),now(),id);
        return finish(actor,id,request.requestId(),digest,"EDIT",row.status(),null,false);
    }
    public View submit(Identity actor,String id,Command request) {
        actor=current(actor);var row=authorized(actor,id,true);owner(actor,row);
        String digest=commandDigest("SUBMIT",id,request);var repeated=repeat(actor,request.requestId(),digest);if(repeated!=null)return repeated;
        version(row,request.expectedVersion());state(row,"DRAFT");
        var task=task(actor,row.taskId(),true);eligible(task);sameSource(row,task);
        String snapshot=snapshotDigest(row);
        reports.jdbc().update("UPDATE detection_quality_report SET status='SUBMITTED',snapshot_sha256=?,submitted_at=?,version=version+1,updated_at=? WHERE report_id=?",snapshot,now(),now(),id);
        return finish(actor,id,request.requestId(),digest,"SUBMIT",row.status(),null,true);
    }
    public View withdraw(Identity actor,String id,Command request) {
        actor=current(actor);var row=authorized(actor,id,true);owner(actor,row);
        String digest=commandDigest("WITHDRAW",id,request);var repeated=repeat(actor,request.requestId(),digest);if(repeated!=null)return repeated;
        version(row,request.expectedVersion());state(row,"SUBMITTED");
        reports.jdbc().update("UPDATE detection_quality_report SET status='WITHDRAWN',version=version+1,updated_at=? WHERE report_id=?",now(),id);
        return finish(actor,id,request.requestId(),digest,"WITHDRAW",row.status(),null,true);
    }
    public View revise(Identity actor,String id,Command request) {
        actor=current(actor);var row=authorized(actor,id,true);owner(actor,row);
        String digest=commandDigest("REVISE",id,request);var repeated=repeat(actor,request.requestId(),digest);if(repeated!=null)return repeated;
        version(row,request.expectedVersion());
        if(!Set.of("REJECTED","WITHDRAWN","APPROVED").contains(row.status()))fail(409,"仅已审批或撤回报告可以创建修订草稿");
        var task=task(actor,row.taskId(),true);eligible(task);
        return newDraft(actor,task,id,row.title(),row.narrative(),request.requestId(),digest);
    }
    public Preview preview(Identity actor,String id,DecisionPreview request) {
        actor=current(actor);supervisor(actor);var row=authorized(actor,id,true);independent(actor,row);
        version(row,request.expectedVersion());state(row,"SUBMITTED");validateDecision(request.decision(),request.reason());integrity(row);
        if("APPROVE".equals(request.decision()))approveGate(row,task(actor,row.taskId(),true));
        Long pending=reports.jdbc().queryForObject("SELECT COUNT(*) FROM detection_report_confirmation WHERE report_id=? AND actor_user_id=? AND expires_at>CURRENT_TIMESTAMP AND used_at IS NULL",Long.class,id,actor.userId());
        if(pending>=20)fail(429,"确认预览过多，请稍后重试");
        String token=UUID.randomUUID().toString().replace("-","")+UUID.randomUUID().toString().replace("-","");
        LocalDateTime expires=now().plusMinutes(10);
        reports.jdbc().update("INSERT INTO detection_report_confirmation(token,report_id,actor_user_id,report_version,snapshot_sha256,decision_sha256,expires_at) VALUES(?,?,?,?,?,?,?)",
                token,id,actor.userId(),row.version(),row.snapshotSha256(),decisionDigest(request.decision(),request.reason()),expires);
        return new Preview(view(row),request.decision(),request.reason().trim(),token,expires);
    }
    public View decide(Identity actor,String id,Decision request) {
        actor=current(actor);supervisor(actor);var row=authorized(actor,id,true);independent(actor,row);
        validateDecision(request.decision(),request.reason());
        String digest=commandDigest("DECIDE",id,request);var repeated=repeat(actor,request.requestId(),digest);if(repeated!=null)return repeated;
        version(row,request.expectedVersion());state(row,"SUBMITTED");integrity(row);
        var confirmations=reports.jdbc().queryForList("SELECT * FROM detection_report_confirmation WHERE token=? FOR UPDATE",request.confirmationToken());
        if(confirmations.isEmpty())fail(409,"请重新预览审批操作");
        var confirmation=confirmations.get(0);
        if(!id.equals(confirmation.get("report_id"))||((Number)confirmation.get("actor_user_id")).longValue()!=actor.userId()
                ||((Number)confirmation.get("report_version")).intValue()!=row.version()||confirmation.get("used_at")!=null
                ||!row.snapshotSha256().equals(confirmation.get("snapshot_sha256"))
                ||!decisionDigest(request.decision(),request.reason()).equals(confirmation.get("decision_sha256")))fail(409,"审批确认与当前内容不一致，请重新预览");
        Long valid=reports.jdbc().queryForObject("SELECT COUNT(*) FROM detection_report_confirmation WHERE token=? AND expires_at>CURRENT_TIMESTAMP",Long.class,request.confirmationToken());
        if(valid!=1)fail(409,"审批确认已过期，请重新预览");
        if("APPROVE".equals(request.decision()))approveGate(row,task(actor,row.taskId(),true));
        String target="APPROVE".equals(request.decision())?"APPROVED":"REJECTED";
        reports.jdbc().update("UPDATE detection_quality_report SET status=?,decided_at=?,decider_user_id=?,decider_username=?,decision_reason=?,version=version+1,updated_at=? WHERE report_id=?",
                target,now(),actor.userId(),actor.username(),request.reason().trim(),now(),id);
        reports.jdbc().update("UPDATE detection_report_confirmation SET used_at=? WHERE token=?",now(),request.confirmationToken());
        return finish(actor,id,request.requestId(),digest,request.decision(),row.status(),request.reason().trim(),true);
    }
    public String export(Identity actor,String id) {
        actor=current(actor);var row=authorized(actor,id,true);state(row,"APPROVED");integrity(row);
        writeAudit(actor,row,"EXPORT",row.status(),null);
        var source=decode(row.sourceJson());
        StringBuilder text=new StringBuilder("# 已审批检测报告\n\n");
        text.append("报告编号：").append(row.reportId()).append("\n\n标题：").append(plain(row.title())).append("\n\n")
                .append("任务：").append(row.taskId()).append("\n\n编写账号：").append(row.ownerUsername())
                .append("\n\n提交时间：").append(row.submittedAt()).append("\n\n审批账号：").append(row.deciderUsername())
                .append("\n\n审批时间：").append(row.decidedAt()).append("\n\n审批意见：").append(plain(row.decisionReason()))
                .append("\n\n快照 SHA-256：").append(row.snapshotSha256()).append("\n\n## 检测依据（提交时快照）\n\n");
        source.forEach((key,value)->text.append("- ").append(SOURCE_LABELS.getOrDefault(key,key)).append("：").append(plain(Objects.toString(value,"未记录"))).append("\n"));
        text.append("\n## 编写意见\n\n").append(plain(row.narrative())).append("\n\n本报告记录人工审批结果，产品放行与公开发布按相应业务流程办理。\n");
        return text.toString();
    }
    private View newDraft(Identity actor,DetectionTask task,String previous,String title,String narrative,String requestId,String digest) {
        String id="qr-"+UUID.randomUUID();LocalDateTime now=now();
        reports.jdbc().update("INSERT INTO detection_quality_report(report_id,previous_report_id,owner_user_id,owner_username,task_id,title,narrative,status,version,source_json,source_sha256,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'DRAFT',1,?,?,?,?)",
                id,previous,actor.userId(),actor.username(),task.getTaskId(),title,narrative,encode(facts(task)),sourceDigest(task),now,now);
        return finish(actor,id,requestId,digest,previous==null?"CREATE":"REVISE",null,null,false);
    }
    private View finish(Identity actor,String id,String requestId,String digest,String action,String before,String reason,boolean event) {
        var row=reports.get(id,false);writeAudit(actor,row,action,before,reason);var response=view(row);
        reports.jdbc().update("INSERT INTO detection_report_command(actor_user_id,request_id,command_sha256,report_id,response_json,created_at) VALUES(?,?,?,?,?,?)",
                actor.userId(),requestId,digest,id,encode(response),now());
        if(event) {
            String eventId=UUID.randomUUID().toString();
            reports.jdbc().update("INSERT INTO detection_report_outbox(event_id,report_id,event_type,payload_json,delivery_status,created_at) VALUES(?,?,?,?,'PENDING',?)",
                    eventId,id,"detection.report."+row.status().toLowerCase(Locale.ROOT)+".v1",
                    encode(Map.of("eventId",eventId,"reportId",id,"actorUserId",actor.userId(),"status",row.status(),"version",row.version(),"schemaVersion",1)),now());
        }
        return response;
    }
    private void writeAudit(Identity actor,Row row,String action,String before,String reason) {
        if(reports.jdbc().update("INSERT INTO detection_report_audit(report_id,actor_user_id,actor_username,action,before_status,after_status,report_version,reason,snapshot_sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                row.reportId(),actor.userId(),actor.username(),action,before,row.status(),row.version(),reason,row.snapshotSha256(),now())!=1)
            throw new IllegalStateException("报告审计写入失败");
    }
    private View repeat(Identity actor,String requestId,String digest) {
        if(requestId==null||!requestId.matches("[A-Za-z0-9_-]{8,64}"))fail(400,"请求编号不正确");
        var rows=reports.jdbc().queryForList("SELECT * FROM detection_report_command WHERE actor_user_id=? AND request_id=?",actor.userId(),requestId);
        if(rows.isEmpty())return null;var command=rows.get(0);
        if(!digest.equals(command.get("command_sha256")))fail(409,"相同请求编号不能用于不同参数");
        authorized(actor,(String)command.get("report_id"),false);
        try{return json.readValue((String)command.get("response_json"),View.class);}catch(Exception error){throw new IllegalStateException("报告请求结果读取失败",error);}
    }
    private Row authorized(Identity actor,String id,boolean lock) {
        if(id==null||!id.matches("qr-[a-f0-9-]{36}"))fail(404,"报告不存在或无访问权限");
        var row=reports.get(id,lock);
        if(row==null||(row.ownerUserId()!=actor.userId()&&(!actor.supervisor()||"DRAFT".equals(row.status()))))fail(404,"报告不存在或无访问权限");
        task(actor,row.taskId(),false);return row;
    }
    private DetectionTask task(Identity actor,String taskId,boolean lock) {
        if(taskId==null||!taskId.matches("[A-Za-z0-9_-]{1,128}"))fail(400,"任务编号不正确");
        var query=new LambdaQueryWrapper<DetectionTask>().eq(DetectionTask::getTaskId,taskId);if(lock)query.last("FOR UPDATE");
        var task=tasks.selectOne(query);
        if(!policy.canAccess(task,actor.username(),actor.supervisor()))fail(404,"任务不存在或无访问权限");return task;
    }
    private Identity current(Identity actor){if(actor==null)throw new SecurityException("请先登录");return users.current(actor.userId(),actor.username());}
    private void owner(Identity actor,Row row){if(actor.userId()!=row.ownerUserId())throw new SecurityException("只有报告本人可以修改草稿或撤回");}
    private void supervisor(Identity actor){if(!actor.supervisor())throw new SecurityException("只有主管可以审批报告");}
    private void independent(Identity actor,Row row){if(actor.userId()==row.ownerUserId())fail(403,"报告需要其他主管独立审批");}
    private void version(Row row,Integer expected){if(expected==null||expected!=row.version())fail(409,"报告版本已更新，请刷新后重试");}
    private void state(Row row,String expected){if(!expected.equals(row.status()))fail(409,"当前报告状态不允许此操作");}
    private void eligible(DetectionTask task){if(!Set.of("COMPLETED","PARTIAL_FAILED").contains(Objects.toString(task.getStatus(),"")))fail(409,"只有已完成或部分失败的检测任务可以编写报告");}
    private void sameSource(Row row,DetectionTask task){if(!row.sourceSha256().equals(sourceDigest(task)))fail(409,"任务依据已变化，请保存草稿更新依据或撤回后创建修订");}
    private void approveGate(Row row,DetectionTask task){
        sameSource(row,task);
        if(!"COMPLETED".equals(task.getStatus())||number(task.getTotalImages())<=0||number(task.getFailedImages())!=0
                ||number(task.getSuccessfulImages())!=number(task.getTotalImages())||number(task.getProcessedImages())!=number(task.getTotalImages())
                ||!"REVIEWED".equals(task.getReviewStatus())||Set.of("RECHECK","NEEDS_RECHECK").contains(Objects.toString(task.getReviewConclusion(),""))
                ||Boolean.TRUE.equals(task.getRecheckRequired())||"REWORK_REQUIRED".equals(task.getFlowStatus()))fail(409,"报告依据尚有未完成检测、复核或复检事项");
    }
    private void integrity(Row row){if(!Objects.equals(row.snapshotSha256(),snapshotDigest(row)))fail(409,"报告快照校验失败，不能审批或导出");}
    private String sourceDigest(DetectionTask task){return digest(task);}
    private String snapshotDigest(Row row){return digest(Map.of("taskId",row.taskId(),"ownerUserId",row.ownerUserId(),"title",row.title(),"narrative",row.narrative(),"source",decode(row.sourceJson()),"sourceSha256",row.sourceSha256()));}
    private String commandDigest(String operation,String id,Object command){return digest(Map.of("operation",operation,"id",id,"command",command));}
    private String decisionDigest(String decision,String reason){return digest(Map.of("decision",decision,"reason",reason.trim()));}
    private String digest(Object value){try{return sha(canonicalJson.writeValueAsString(value));}catch(Exception error){throw new IllegalStateException("报告摘要计算失败",error);}}
    private View view(Row r){return new View(r.reportId(),r.previousReportId(),r.ownerUserId(),r.ownerUsername(),r.taskId(),r.title(),r.narrative(),r.status(),r.version(),decode(r.sourceJson()),r.sourceSha256(),r.snapshotSha256(),r.submittedAt(),r.decidedAt(),r.deciderUsername(),r.decisionReason(),r.createdAt(),r.updatedAt());}
    private Map<String,Object> facts(DetectionTask t){
        var facts=new LinkedHashMap<String,Object>();facts.put("taskId",t.getTaskId());facts.put("dispatchId",t.getDispatchId());
        facts.put("modelId",t.getModelId());facts.put("modelVersion",t.getModelVersion());facts.put("detectionStatus",t.getStatus());
        facts.put("totalImages",t.getTotalImages());facts.put("processedImages",t.getProcessedImages());facts.put("successfulImages",t.getSuccessfulImages());
        facts.put("failedImages",t.getFailedImages());facts.put("defectCount",t.getDefectCount());facts.put("reviewStatus",t.getReviewStatus());
        facts.put("reviewConclusion",t.getReviewConclusion());facts.put("reviewer",t.getReviewer());facts.put("reviewedAt",Objects.toString(t.getReviewedAt(),null));
        facts.put("confirmedDefectCount",t.getConfirmedDefectCount());facts.put("falsePositiveCount",t.getFalsePositiveCount());
        facts.put("flowStatus",t.getFlowStatus());facts.put("dispositionStatus",t.getDispositionStatus());facts.put("dispositionAction",t.getDispositionAction());
        facts.put("recheckRequired",t.getRecheckRequired());facts.put("finishedAt",Objects.toString(t.getFinishedAt(),null));return facts;
    }
    private static int number(Integer n){return n==null?0:n;}
    private static final Map<String,String> SOURCE_LABELS=Map.ofEntries(
            Map.entry("taskId","任务编号"),Map.entry("dispatchId","检测运行编号"),Map.entry("modelId","模型编号"),Map.entry("modelVersion","模型版本"),
            Map.entry("detectionStatus","检测状态"),Map.entry("totalImages","图片总数"),Map.entry("processedImages","已处理图片"),Map.entry("successfulImages","成功图片"),
            Map.entry("failedImages","失败图片"),Map.entry("defectCount","缺陷数量"),Map.entry("reviewStatus","人工复核状态"),Map.entry("reviewConclusion","复核结论"),
            Map.entry("reviewer","复核账号"),Map.entry("reviewedAt","复核时间"),Map.entry("confirmedDefectCount","确认缺陷数"),Map.entry("falsePositiveCount","误报数"),
            Map.entry("flowStatus","流转状态"),Map.entry("dispositionStatus","处置状态"),Map.entry("dispositionAction","处置措施"),Map.entry("recheckRequired","是否需要复检"),Map.entry("finishedAt","检测完成时间"));
    private static LocalDateTime now(){return LocalDateTime.now().truncatedTo(ChronoUnit.SECONDS);}
    private static void validateText(String title,String narrative){if(title==null||title.isBlank()||title.length()>120||narrative==null||narrative.isBlank()||narrative.length()>10000)fail(400,"报告标题或意见不正确");}
    private static void validateDecision(String decision,String reason){if(!Set.of("APPROVE","REJECT").contains(Objects.toString(decision,""))||reason==null||reason.isBlank()||reason.length()>500)fail(400,"审批决定及意见不正确");}
    private String encode(Object value){try{return json.writeValueAsString(value);}catch(Exception error){throw new IllegalStateException("报告数据编码失败",error);}}
    private Map<String,Object> decode(String value){try{return json.readValue(value,new TypeReference<LinkedHashMap<String,Object>>(){});}catch(Exception error){throw new IllegalStateException("报告依据读取失败",error);}}
    private static String sha(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(Exception error){throw new IllegalStateException(error);}}
    private static String plain(String value){return Objects.toString(value,"").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("\\","\\\\").replace("`","\\`").replace("*","\\*").replace("_","\\_").replace("[","\\[").replace("]","\\]").replace("#","\\#");}
    private static void fail(int code,String message){throw new BusinessException(code,message);}
}
