package com.ruanzhu.doorhandle.module.detection.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity;
import com.ruanzhu.doorhandle.module.detection.dto.report.QualityReportDtos.*;
import com.ruanzhu.doorhandle.module.detection.dto.report.ReportTime;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.repository.QualityReportRepository;
import com.ruanzhu.doorhandle.module.detection.repository.QualityReportRepository.Row;
import com.ruanzhu.doorhandle.module.detection.repository.ReportWorkflowRepository;
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
    private final ReportWorkflowRepository workflow;
    @org.springframework.beans.factory.annotation.Autowired private org.springframework.beans.factory.ObjectProvider<com.ruanzhu.doorhandle.contracts.agent.OperationsAuditApi> operationsAudit;
    @org.springframework.beans.factory.annotation.Value("${operations.audit.enabled:false}") private boolean operationsAuditEnabled;
    @org.springframework.beans.factory.annotation.Value("${collaboration.change-history.enabled:false}") private boolean changeHistoryEnabled;
    @org.springframework.beans.factory.annotation.Value("${collaboration.mutations.enabled:false}") private boolean collaborationMutationsEnabled;
    @org.springframework.beans.factory.annotation.Autowired private ReportDocumentRenderer documentRenderer;
    public QualityReportService(QualityReportRepository reports,DetectionTaskMapper tasks,BusinessUserDirectory users,
            DetectionTaskAccessPolicy policy,ObjectMapper json) {
        this.reports=reports;this.tasks=tasks;this.users=users;this.policy=policy;this.json=json;
        this.workflow=new ReportWorkflowRepository(reports.jdbc(),json);
        this.canonicalJson=json.copy().configure(com.fasterxml.jackson.databind.SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS,true)
                .configure(com.fasterxml.jackson.databind.MapperFeature.SORT_PROPERTIES_ALPHABETICALLY,true);
    }
    public Map<String,Object> list(Identity actor,int page,int size,String status,String keyword) {
        actor=current(actor);
        if(page<1||page>10000||size<1||size>100||(keyword!=null&&keyword.length()>128))fail(400,"查询参数不正确");
        if(status!=null&&!status.isBlank()&&!Set.of("DRAFT","SUBMITTED","APPROVED","REJECTED","WITHDRAWN").contains(status))fail(400,"报告状态不正确");
        var params=new HashMap<String,Object>();params.put("owner",actor.userId());params.put("username",actor.username());
        String where="(r.owner_user_id=:owner"+(actor.supervisor()?" OR r.status<>'DRAFT'":"")+")";
        if(!actor.supervisor())where+=" AND "+policy.actorPredicate("t.",policy.stableIdentityActive()?":owner":":username",":owner");
        if(status!=null&&!status.isBlank()){where+=" AND r.status=:status";params.put("status",status);}
        if(keyword!=null&&!keyword.isBlank()){where+=" AND (r.task_id LIKE :keyword OR r.title LIKE :keyword)";params.put("keyword","%"+keyword.trim()+"%");}
        var rows=reports.list(where,params,page,size);
        return Map.of("records",rows.stream().map(this::view).toList(),"total",reports.count(where,params),"page",page,"size",size);
    }
    public View get(Identity actor,String id) { actor=current(actor);return view(authorized(actor,id,false)); }
    public List<EventDelivery> events(Identity actor,String id) {
        actor=current(actor);authorized(actor,id,false);
        return workflow.events(id);
    }
    public List<EventDelivery> retryEvent(Identity actor,String id,String eventId,RetryEvent request) {
        actor=current(actor);supervisor(actor);var row=authorized(actor,id,true);
        if(eventId==null||!eventId.matches("[a-f0-9-]{36}")||request==null||request.expectedAttempts()==null||request.expectedAttempts()<0||!request.confirmed())fail(400,"请核对事件并明确确认重试");
        String digest=commandDigest("EVENT_RETRY",id+":"+eventId,request);
        if(repeat(actor,request.requestId(),digest)!=null)return events(actor,id);
        if(!workflow.retry(id,eventId,request.expectedAttempts()))
            fail(409,"事件已变化或正在发送，请刷新后重试");
        writeAudit(actor,row,"EVENT_RETRY",row.status(),"人工确认重新投递报告事件");
        businessAudit(actor,row,row,"EVENT_RETRY",request.requestId());
        workflow.saveCommand(actor.userId(),request.requestId(),digest,row,encode(view(row)));
        return events(actor,id);
    }
    public List<Audit> audit(Identity actor,String id) {
        actor=current(actor);authorized(actor,id,false);
        return workflow.audit(id);
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
        reports.jdbc().update("UPDATE quality_report SET title=?,narrative=?,source_json=?,source_sha256=?,version=version+1,updated_at=? WHERE report_id=?",
                request.title().trim(),request.narrative(),encode(facts(task)),sourceDigest(task),now(),id);
        return finish(actor,id,request.requestId(),digest,"EDIT",row,null,false);
    }
    public View submit(Identity actor,String id,Command request) {
        actor=current(actor);var row=authorized(actor,id,true);owner(actor,row);
        String digest=commandDigest("SUBMIT",id,request);var repeated=repeat(actor,request.requestId(),digest);if(repeated!=null)return repeated;
        version(row,request.expectedVersion());state(row,"DRAFT");
        var task=task(actor,row.taskId(),true);eligible(task);sameSource(row,task);
        String snapshot=snapshotDigest(row);
        reports.jdbc().update("UPDATE quality_report SET status='SUBMITTED',snapshot_sha256=?,submitted_at=?,version=version+1,updated_at=? WHERE report_id=?",snapshot,now(),now(),id);
        return finish(actor,id,request.requestId(),digest,"SUBMIT",row,null,true);
    }
    public View withdraw(Identity actor,String id,Command request) {
        actor=current(actor);var row=authorized(actor,id,true);owner(actor,row);
        String digest=commandDigest("WITHDRAW",id,request);var repeated=repeat(actor,request.requestId(),digest);if(repeated!=null)return repeated;
        version(row,request.expectedVersion());state(row,"SUBMITTED");
        reports.jdbc().update("UPDATE quality_report SET status='WITHDRAWN',version=version+1,updated_at=? WHERE report_id=?",now(),id);
        return finish(actor,id,request.requestId(),digest,"WITHDRAW",row,null,true);
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
        String token=UUID.randomUUID().toString().replace("-","")+UUID.randomUUID().toString().replace("-","");
        LocalDateTime expires=workflow.confirmation(actor.userId(),row,token,decisionDigest(request.decision(),request.reason()));
        return new Preview(view(row),request.decision(),request.reason().trim(),token,ReportTime.fromUtc(expires));
    }
    public View decide(Identity actor,String id,Decision request) {
        actor=current(actor);supervisor(actor);var row=authorized(actor,id,true);independent(actor,row);
        validateDecision(request.decision(),request.reason());
        String digest=commandDigest("DECIDE",id,request);var repeated=repeat(actor,request.requestId(),digest);if(repeated!=null)return repeated;
        version(row,request.expectedVersion());state(row,"SUBMITTED");integrity(row);
        var confirmation=workflow.requireConfirmation(actor.userId(),row,request.confirmationToken(),decisionDigest(request.decision(),request.reason()));
        if("APPROVE".equals(request.decision()))approveGate(row,task(actor,row.taskId(),true));
        String target="APPROVE".equals(request.decision())?"APPROVED":"REJECTED";
        reports.jdbc().update("UPDATE quality_report SET status=?,decided_at=?,decider_user_id=?,decider_username=?,decision_reason=?,version=version+1,updated_at=? WHERE report_id=?",
                target,now(),actor.userId(),actor.username(),request.reason().trim(),now(),id);
        workflow.consumeConfirmation(confirmation);
        return finish(actor,id,request.requestId(),digest,request.decision(),row,request.reason().trim(),true);
    }
    public String export(Identity actor,String id) {
        return exportText(actor,id,null);
    }
    private String exportText(Identity actor,String id,String reason) {
        actor=current(actor);var row=authorized(actor,id,true);state(row,"APPROVED");integrity(row);
        writeAudit(actor,row,"EXPORT",row.status(),reason);
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
    public ReportDocumentRenderer.File exportDocument(Identity actor,String id,String format) {
        if(!Set.of("docx","pdf","xlsx").contains(format))fail(400,"报告格式不正确");
        // Same authorization, approved state, frozen hash checks and audit transaction as Markdown.
        return documentRenderer.render(exportText(actor,id,"文件格式："+format.toUpperCase(Locale.ROOT)),format);
    }
    private View newDraft(Identity actor,DetectionTask task,String previous,String title,String narrative,String requestId,String digest) {
        String id="qr-"+UUID.randomUUID();LocalDateTime now=now();
        reports.jdbc().update("INSERT INTO quality_report(report_id,previous_report_id,owner_user_id,owner_username,task_id,title,narrative,status,version,source_json,source_sha256,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'DRAFT',1,?,?,?,?)",
                id,previous,actor.userId(),actor.username(),task.getTaskId(),title,narrative,encode(facts(task)),sourceDigest(task),now,now);
        return finish(actor,id,requestId,digest,previous==null?"CREATE":"REVISE",null,null,false);
    }
    private View finish(Identity actor,String id,String requestId,String digest,String action,Row before,String reason,boolean event) {
        var row=reports.get(id,false);writeAudit(actor,row,action,before==null?null:before.status(),reason);businessAudit(actor,before,row,action,requestId);var response=view(row);
        workflow.saveCommand(actor.userId(),requestId,digest,row,encode(response));
        if(event) {
            String eventId=UUID.randomUUID().toString();
            workflow.enqueue(row,actor.userId(),eventId,"detection.report."+row.status().toLowerCase(Locale.ROOT)+".v1",
                    encode(Map.of("eventId",eventId,"reportId",id,"actorUserId",actor.userId(),"status",row.status(),"version",row.version(),"schemaVersion",1)));
        }
        return response;
    }
    private void writeAudit(Identity actor,Row row,String action,String before,String reason) {
        workflow.audit(row,actor.userId(),actor.username(),action,before,reason);
    }
    /** Only new commands reach here; a duplicate command returns its immutable original response earlier. */
    private void businessAudit(Identity actor,Row before,Row row,String action,String request){
        if(!operationsAuditEnabled)return;
        var api=operationsAudit==null?null:operationsAudit.getIfAvailable();if(api==null)throw new IllegalStateException("必要业务审计服务不可用");
        String scope="DRAFT".equals(row.status())?"PRIVATE":"ENTERPRISE";
        var metadata=new com.ruanzhu.doorhandle.contracts.agent.OperationsAuditApi.Event(new com.ruanzhu.doorhandle.contracts.agent.AgentActor(actor.userId(),actor.username(),actor.supervisor()?com.ruanzhu.doorhandle.contracts.agent.AgentActor.Role.SUPERVISOR:com.ruanzhu.doorhandle.contracts.agent.AgentActor.Role.INSPECTOR),scope,"QUALITY_REPORT",action,row.reportId(),request,"APPLIED",(long)row.version());
        if(!changeHistoryEnabled&&!collaborationMutationsEnabled){api.append(metadata);return;}
        var previous=before==null?Map.<String,Object>of():historyFields(before);var current=historyFields(row);
        var changes=new ArrayList<com.ruanzhu.doorhandle.contracts.collaboration.ChangeHistory.Change>();
        for(var entry:current.entrySet()){
            String field=entry.getKey();Object old=previous.get(field),value=entry.getValue();
            if(before!=null&&Objects.equals(old,value))continue;
            changes.add(new com.ruanzhu.doorhandle.contracts.collaboration.ChangeHistory.Change(field,REPORT_FIELD_LABELS.get(field),before==null?"ADD":"REPLACE",old,value,"STRING",false));
        }
        var receipt=api.appendChangeWithReceipt(new com.ruanzhu.doorhandle.contracts.agent.OperationsAuditApi.ChangeEvent(metadata,"QUALITY_REPORT",null,before==null?null:(long)before.version(),changes));
        reportReceipt(receipt,row.version());
    }
    private static final Map<String,String> REPORT_FIELD_LABELS=Map.ofEntries(
            Map.entry("title","报告标题"),Map.entry("status","报告状态"),Map.entry("taskId","检测任务"),
            Map.entry("previousReportId","原报告"),Map.entry("ownerUserId","编写账号"),Map.entry("narrativeSha256","编写意见内容摘要"),
            Map.entry("sourceSha256","检测依据摘要"),Map.entry("snapshotSha256","提交快照摘要"),
            Map.entry("deciderUsername","审批账号"),Map.entry("decisionReason","审批意见"));
    private static Map<String,Object> historyFields(Row row){
        var fields=new LinkedHashMap<String,Object>();fields.put("title",row.title());fields.put("status",row.status());
        fields.put("taskId",row.taskId());fields.put("previousReportId",row.previousReportId());fields.put("ownerUserId",Long.toString(row.ownerUserId()));
        fields.put("narrativeSha256",sha(row.narrative()));fields.put("sourceSha256",row.sourceSha256());fields.put("snapshotSha256",row.snapshotSha256());
        fields.put("deciderUsername",row.deciderUsername());fields.put("decisionReason",row.decisionReason());return fields;
    }
    private View repeat(Identity actor,String requestId,String digest) {
        if(requestId==null||!requestId.matches("[A-Za-z0-9_-]{8,64}"))fail(400,"请求编号不正确");
        var stored=workflow.command(actor.userId(),requestId);if(stored.isEmpty())return null;var command=stored.get();
        if(!digest.equals(command.requestSha256()))fail(409,"相同请求编号不能用于不同参数");
        authorized(actor,command.resourceId(),false);
        final View response;
        try{response=json.readValue(workflow.commandPayload(command).responseJson(),View.class);}catch(Exception error){throw new IllegalStateException("报告请求结果读取失败",error);}
        // Only the report's immutable command and digest establish an exact replay.
        // The audit lookup supplements it with the original response metadata.
        if(operationsAuditEnabled&&(changeHistoryEnabled||collaborationMutationsEnabled)){
            var api=operationsAudit==null?null:operationsAudit.getIfAvailable();
            if(api==null)throw new IllegalStateException("必要业务审计服务不可用");
            var receipt=api.findChangeReceipt(new com.ruanzhu.doorhandle.contracts.agent.AgentActor(actor.userId(),actor.username(),actor.supervisor()?com.ruanzhu.doorhandle.contracts.agent.AgentActor.Role.SUPERVISOR:com.ruanzhu.doorhandle.contracts.agent.AgentActor.Role.INSPECTOR),
                    "QUALITY_REPORT","QUALITY_REPORT",command.resourceId(),requestId);
            if(receipt==null)fail(409,"原始报告修改回执未确认，请保留请求编号核对");
            reportReceipt(receipt,response.version());
        }
        return response;
    }
    private void reportReceipt(com.ruanzhu.doorhandle.contracts.agent.OperationsAuditApi.ChangeReceipt receipt,int version){
        if(receipt==null||receipt.auditId()==null||receipt.eventId()==null||!Integer.toString(version).equals(receipt.resourceVersion()))
            throw new IllegalStateException("报告修改回执与原始业务版本不一致");
        var attributes=org.springframework.web.context.request.RequestContextHolder.getRequestAttributes();
        if(attributes instanceof org.springframework.web.context.request.ServletRequestAttributes servlet&&servlet.getResponse()!=null){
            servlet.getResponse().setHeader("X-Audit-ID",receipt.auditId());
            servlet.getResponse().setHeader("X-Change-Event-ID",receipt.eventId());
            servlet.getResponse().setHeader("X-Resource-Version",receipt.resourceVersion());
        }
    }
    private Row authorized(Identity actor,String id,boolean lock) {
        if(id==null||!id.matches("qr-[a-f0-9-]{36}"))fail(404,"报告不存在或无访问权限");
        var row=reports.get(id,lock);
        if(row==null||(row.ownerUserId()!=actor.userId()&&(!actor.supervisor()||"DRAFT".equals(row.status()))))fail(404,"报告不存在或无访问权限");
        task(actor,row.taskId(),lock);return row;
    }
    private DetectionTask task(Identity actor,String taskId,boolean lock) {
        if(taskId==null||!taskId.matches("[A-Za-z0-9_-]{1,128}"))fail(400,"任务编号不正确");
        var query=new LambdaQueryWrapper<DetectionTask>().eq(DetectionTask::getTaskId,taskId);if(lock)query.last("FOR UPDATE");
        var task=tasks.selectOne(query);
        var principal=new com.ruanzhu.doorhandle.contracts.agent.AgentActor(actor.userId(),actor.username(),actor.supervisor()?com.ruanzhu.doorhandle.contracts.agent.AgentActor.Role.SUPERVISOR:com.ruanzhu.doorhandle.contracts.agent.AgentActor.Role.INSPECTOR);
        if(!policy.canAccess(task,principal))fail(404,"任务不存在或无访问权限");
        if(lock)policy.assertCanMutate(task,principal);return task;
    }
    private Identity current(Identity actor){if(actor==null)throw new SecurityException("请先登录");return changeHistoryEnabled||collaborationMutationsEnabled?users.lockCurrent(actor.userId(),actor.username()):users.current(actor.userId(),actor.username());}
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
    private static LocalDateTime now(){return LocalDateTime.now(ReportTime.BEIJING).truncatedTo(ChronoUnit.SECONDS);}
    private static void validateText(String title,String narrative){if(title==null||title.isBlank()||title.length()>120||narrative==null||narrative.isBlank()||narrative.length()>10000)fail(400,"报告标题或意见不正确");}
    private static void validateDecision(String decision,String reason){if(!Set.of("APPROVE","REJECT").contains(Objects.toString(decision,""))||reason==null||reason.isBlank()||reason.length()>500)fail(400,"审批决定及意见不正确");}
    private String encode(Object value){try{return json.writeValueAsString(value);}catch(Exception error){throw new IllegalStateException("报告数据编码失败",error);}}
    private Map<String,Object> decode(String value){try{return json.readValue(value,new TypeReference<LinkedHashMap<String,Object>>(){});}catch(Exception error){throw new IllegalStateException("报告依据读取失败",error);}}
    private static String sha(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(Exception error){throw new IllegalStateException(error);}}
    private static String plain(String value){return Objects.toString(value,"").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("\\","\\\\").replace("`","\\`").replace("*","\\*").replace("_","\\_").replace("[","\\[").replace("]","\\]").replace("#","\\#");}
    private static void fail(int code,String message){throw new BusinessException(code,message);}
}
