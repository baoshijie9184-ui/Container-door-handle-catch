package com.ruanzhu.doorhandle.module.detection.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.framework.persistence.workflow.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.scheduling.support.CronExpression;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.*;
import java.util.*;

/** Durable quality snapshots using the shared schedule/workflow protocol, with independent domain checks. */
@Service
@ConditionalOnProperty(prefix="app.quality-automation",name="enabled",havingValue="true")
public class QualityDigestService {
    private static final ZoneId DISPLAY_ZONE=ZoneId.of("Asia/Shanghai");
    private static final org.slf4j.Logger log=org.slf4j.LoggerFactory.getLogger(QualityDigestService.class);
    private static final String PLAN_COLUMNS="id,plan_id AS schedule_id,owner_user_id,owner_name AS owner_username,name,cron_expression,enabled,revision AS version,next_fire_at,created_at,updated_at,time_zone,payload_version,payload_json";
    private final JdbcTemplate jdbc;
    private final BusinessUserDirectory users;
    private final ObjectMapper json;
    private final TransactionTemplate transactions;
    private final ReportDocumentRenderer renderer;
    private final ZoneId taskZone;
    private final JdbcWorkflowStore workflows;
    private final JdbcAuditStore audits;

    public record DigestRunV1(String scheduleId,String scheduledFor,String reportDate) {
        public DigestRunV1 {
            if(scheduleId==null||scheduleId.isBlank()||scheduleId.length()>64)throw new IllegalArgumentException("日报计划编号无效");
            LocalDateTime.parse(scheduledFor);LocalDate.parse(reportDate);
        }
    }
    public record DigestCommandV1(String scheduleId) {
        public DigestCommandV1 { if(scheduleId==null||scheduleId.isBlank()||scheduleId.length()>64)throw new IllegalArgumentException("日报计划编号无效"); }
    }
    public record DigestAuditV1(String cron,Boolean enabled,String runId,String reportDate,String format,String snapshotSha256) { }

    public QualityDigestService(JdbcTemplate jdbc,BusinessUserDirectory users,ObjectMapper json,PlatformTransactionManager manager,
            ReportDocumentRenderer renderer,@Value("${app.quality-automation.task-time-zone:UTC}")String taskZone) {
        this.jdbc=jdbc;this.users=users;this.json=json.copy().enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS);
        this.transactions=new TransactionTemplate(manager);this.renderer=renderer;this.taskZone=ZoneId.of(taskZone);
        var protocols=WorkflowProtocols.defaults()
            .with(new WorkflowProtocol<>(WorkflowKind.DIGEST_RUN,1,DigestRunV1.class,Set.of("PENDING"),Set.of("COMPLETED","FAILED","BLOCKED"),
                Map.of("PENDING",Set.of("RUNNING"),"RUNNING",Set.of("RUNNING","COMPLETED","FAILED","BLOCKED")),value->{},true))
            .with(new WorkflowProtocol<>(WorkflowKind.DIGEST_COMMAND,1,DigestCommandV1.class,Set.of("COMPLETED"),Set.of("COMPLETED"),Map.of(),value->{}));
        this.workflows=new JdbcWorkflowStore(jdbc,this.json,protocols);
        this.audits=new JdbcAuditStore(jdbc,this.json,Map.of("DIGEST",DigestAuditV1.class));
    }
    private List<Map<String,Object>> rows(String sql,Object... arguments){return jdbc.query(sql,com.ruanzhu.doorhandle.common.LocalDateTimeRow::read,arguments);}
    private static LocalDateTime now(){return LocalDateTime.now(ZoneOffset.UTC).truncatedTo(java.time.temporal.ChronoUnit.MICROS);}
    private BusinessUserDirectory.Identity actor(){var actor=users.authenticated();actor=users.current(actor.userId(),actor.username());if(!actor.supervisor())throw fail(403,"仅主管可管理质检日报");return actor;}
    private Map<String,Object> owned(String id,long user,boolean lock) {
        var found=rows("SELECT "+PLAN_COLUMNS+" FROM scheduled_plan WHERE kind='DIGEST_SCHEDULE' AND plan_id=? AND owner_user_id=?"+(lock?" FOR UPDATE":""),id,user);
        if(found.isEmpty())throw fail(404,"计划不存在或无访问权限");validatePlan(found.get(0));return found.get(0);
    }
    private void validatePlan(Map<String,Object> plan) {
        if(!DISPLAY_ZONE.getId().equals(plan.get("time_zone"))||!(plan.get("payload_version") instanceof Number number)||number.intValue()!=1)
            throw fail(409,"日报计划协议或时区不匹配");
        try {var body=json.readTree(Objects.toString(plan.get("payload_json"),""));if(body==null||!body.isObject()||!body.isEmpty())throw fail(409,"日报计划载荷不正确");}
        catch(com.fasterxml.jackson.core.JsonProcessingException error){throw fail(409,"日报计划载荷无法读取");}
    }
    private Map<String,Object> planView(Map<String,Object> plan){var view=new LinkedHashMap<>(plan);view.remove("time_zone");view.remove("payload_version");view.remove("payload_json");return view;}
    public List<Map<String,Object>> schedules(){var result=rows("SELECT "+PLAN_COLUMNS+" FROM scheduled_plan WHERE kind='DIGEST_SCHEDULE' AND owner_user_id=? ORDER BY id DESC LIMIT 100",actor().userId());result.forEach(this::validatePlan);return result.stream().map(this::planView).toList();}
    public record Save(String name,String cronExpression,boolean enabled,int expectedVersion,String requestId){}
    public Map<String,Object> save(String id,Save request) {
        var caller=actor();
        if(request==null||request.name()==null||request.name().isBlank()||request.name().length()>120||request.cronExpression()==null||request.cronExpression().length()>100)throw fail(400,"计划名称或时间表达式不正确");
        requestId(request.requestId());var cron=cron(request.cronExpression());String digest=sha(Objects.toString(id,"")+"\n"+write(request));
        return transactions.execute(status->{
            var fresh=users.lockCurrent(caller.userId(),caller.username());if(!fresh.supervisor())throw fail(403,"当前账号已无主管权限");control();
            var repeated=workflows.findByRequest(WorkflowKind.DIGEST_COMMAND,JdbcWorkflowStore.ownerScope(fresh.userId()),request.requestId());
            if(repeated.isPresent()) {
                var command=repeated.get();if(!digest.equals(command.requestSha256()))throw fail(409,"请求编号已用于其他计划操作");
                var payload=workflows.payload(command,DigestCommandV1.class);
                if(!"SCHEDULE".equals(command.resourceType())||!payload.scheduleId().equals(command.resourceId())||command.ownerUserId()!=fresh.userId())throw fail(409,"计划操作回执归属不匹配");
                return planView(owned(payload.scheduleId(),fresh.userId(),false));
            }
            String scheduleId=id;
            if(scheduleId==null) {
                if(request.expectedVersion()!=0)throw fail(409,"新计划的版本应为零");
                if(jdbc.queryForObject("SELECT COUNT(*) FROM scheduled_plan WHERE kind='DIGEST_SCHEDULE' AND owner_user_id=?",Long.class,fresh.userId())>=50)throw fail(409,"最多保留 50 个计划");
                scheduleId="qs-"+UUID.randomUUID();
                jdbc.update("INSERT INTO scheduled_plan(plan_id,kind,owner_user_id,owner_name,name,cron_expression,time_zone,enabled,revision,next_fire_at,payload_version,payload_json,created_at,updated_at) VALUES(?,'DIGEST_SCHEDULE',?,?,?,?,?,?,1,?,1,'{}',?,?)",
                    scheduleId,fresh.userId(),fresh.username(),request.name().strip(),request.cronExpression().strip(),DISPLAY_ZONE.getId(),request.enabled(),request.enabled()?next(cron):null,now(),now());
            } else {
                var prior=owned(scheduleId,fresh.userId(),true);
                scheduleId=prior.get("schedule_id").toString();
                if(((Number)prior.get("version")).longValue()!=request.expectedVersion())throw fail(409,"计划已更新，请重新读取");
                if(jdbc.update("UPDATE scheduled_plan SET name=?,cron_expression=?,enabled=?,revision=revision+1,next_fire_at=?,updated_at=? WHERE kind='DIGEST_SCHEDULE' AND plan_id=? AND owner_user_id=? AND revision=?",
                    request.name().strip(),request.cronExpression().strip(),request.enabled(),request.enabled()?next(cron):null,now(),scheduleId,fresh.userId(),request.expectedVersion())!=1)throw fail(409,"计划已更新，请重新读取");
            }
            workflows.create(new WorkflowDraft(UUID.randomUUID().toString(),WorkflowKind.DIGEST_COMMAND,JdbcWorkflowStore.ownerScope(fresh.userId()),request.requestId(),digest,
                fresh.userId(),fresh.userId(),null,"SCHEDULE",scheduleId,(long)request.expectedVersion()+1,null,null,"COMPLETED",null,1,new DigestCommandV1(scheduleId)));
            audit(scheduleId,fresh.userId(),"SAVE",request.expectedVersion()+1,new DigestAuditV1(request.cronExpression(),request.enabled(),null,null,null,null));
            return planView(owned(scheduleId,fresh.userId(),false));
        });
    }
    public record Generate(LocalDate reportDate,int expectedVersion,String requestId){}
    public Map<String,Object> generate(String id,Generate request) {
        var caller=actor();if(request==null)throw fail(400,"日报请求不正确");requestId(request.requestId());
        if(request.reportDate()==null||request.reportDate().isAfter(LocalDate.now(DISPLAY_ZONE))||request.reportDate().isBefore(LocalDate.now(DISPLAY_ZONE).minusYears(10)))throw fail(400,"日报日期不正确");
        return transactions.execute(status->{
            var fresh=users.lockCurrent(caller.userId(),caller.username());if(!fresh.supervisor())throw fail(403,"当前账号已无主管权限");control();
            var schedule=owned(id,fresh.userId(),true);String scheduleId=schedule.get("schedule_id").toString();String key="manual:"+request.requestId();
            var repeated=workflows.findByRequest(WorkflowKind.DIGEST_RUN,"SCHEDULE:"+scheduleId,key);
            if(repeated.isPresent()) {
                var prior=repeated.get();var payload=runPayload(prior);
                if(prior.ownerUserId()!=fresh.userId()||!scheduleId.equals(owned(payload.scheduleId(),fresh.userId(),false).get("schedule_id"))||!request.reportDate().toString().equals(payload.reportDate()))throw fail(409,"请求编号已用于其他日期");
                return Map.of("runId",prior.workflowId(),"status","QUEUED_OR_EXISTING");
            }
            if(((Number)schedule.get("version")).longValue()!=request.expectedVersion())throw fail(409,"计划已更新，请重新读取");
            quota(fresh.userId());String run=enqueue(scheduleId,fresh.userId(),key,now(),request.reportDate());
            audit(scheduleId,fresh.userId(),"GENERATE",request.expectedVersion(),new DigestAuditV1(null,null,run,request.reportDate().toString(),null,null));
            return Map.of("runId",run,"status","PENDING");
        });
    }
    private String enqueue(String id,long owner,String key,LocalDateTime slot,LocalDate date) {
        String run="qd-"+UUID.randomUUID();var payload=new DigestRunV1(id,slot.toString(),date.toString());
        return workflows.create(new WorkflowDraft(run,WorkflowKind.DIGEST_RUN,"SCHEDULE:"+id,key,sha(write(List.of(id,key,date.toString()))),owner,owner,null,
            "SCHEDULE",id,null,null,run,"PENDING",null,1,payload),new WorkflowTiming(date,slot)).workflowId();
    }
    private DigestRunV1 runPayload(WorkflowRecord run) {
        var payload=workflows.payload(run,DigestRunV1.class);
        if(!"SCHEDULE".equals(run.resourceType())||!payload.scheduleId().equals(run.resourceId())
            ||!LocalDate.parse(payload.reportDate()).equals(run.effectiveDate())||!LocalDateTime.parse(payload.scheduledFor()).equals(run.scheduledFor()))throw fail(409,"日报运行身份或日期不匹配");
        return payload;
    }
    public List<Map<String,Object>> runs(String id){var caller=actor();owned(id,caller.userId(),false);return rows("SELECT workflow_id AS run_id,effective_date AS report_date,status,result_sha256 AS snapshot_sha256,error_code,created_at,finished_at FROM workflow_instance WHERE kind='DIGEST_RUN' AND resource_type='SCHEDULE' AND digest_schedule_id=? AND owner_user_id=? ORDER BY id DESC LIMIT 100",id,caller.userId());}
    @Scheduled(fixedDelayString="${app.quality-automation.poll-ms:30000}")
    public void pump(){try{for(int i=0;i<3;i++)allocate();for(int i=0;i<2;i++)work();}catch(RuntimeException error){log.warn("质检日报调度暂不可用；保留持久状态等待下一调度周期");}}
    private void allocate() {
        transactions.executeWithoutResult(status->{
            control();var due=rows("SELECT "+PLAN_COLUMNS+" FROM scheduled_plan WHERE kind='DIGEST_SCHEDULE' AND enabled=TRUE AND next_fire_at<=? ORDER BY next_fire_at,id LIMIT 1 FOR UPDATE SKIP LOCKED",now());
            if(due.isEmpty())return;var plan=due.get(0);validatePlan(plan);String id=plan.get("schedule_id").toString();long owner=((Number)plan.get("owner_user_id")).longValue();
            String blocked=null;
            try{if(!users.current(owner,plan.get("owner_username").toString()).supervisor())throw new SecurityException();}
            catch(SecurityException error){blocked="PERMISSION_BLOCKED";}
            if(blocked==null)try{quota(owner);}catch(BusinessException error){blocked="RUN_QUOTA_BLOCKED";}
            if(blocked!=null){jdbc.update("UPDATE scheduled_plan SET enabled=FALSE,revision=revision+1,updated_at=? WHERE kind='DIGEST_SCHEDULE' AND plan_id=?",now(),id);audit(id,owner,blocked,((Number)plan.get("version")).intValue(),new DigestAuditV1(null,null,null,null,null,null));return;}
            LocalDateTime slot=time(plan.get("next_fire_at"));var date=slot.atOffset(ZoneOffset.UTC).atZoneSameInstant(DISPLAY_ZONE).toLocalDate().minusDays(1);
            enqueue(id,owner,"scheduled:"+slot,slot,date);
            jdbc.update("UPDATE scheduled_plan SET next_fire_at=?,updated_at=? WHERE kind='DIGEST_SCHEDULE' AND plan_id=?",next(cron(plan.get("cron_expression").toString())),now(),id);
        });
    }
    private void work() {
        var claim=transactions.execute(status->{
            var found=rows("SELECT workflow_id FROM workflow_instance WHERE kind='DIGEST_RUN' AND (status='PENDING' OR (status='RUNNING' AND lease_expires_at<=UTC_TIMESTAMP(6))) ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED");
            if(found.isEmpty())return null;
            var before=workflows.find(WorkflowKind.DIGEST_RUN,found.get(0).get("workflow_id").toString()).orElseThrow();var payload=runPayload(before);
            return "RUNNING".equals(before.status())?workflows.reclaim(before,"RUNNING",payload,before.runId(),null,Duration.ofMinutes(5))
                :workflows.claim(before,"RUNNING",payload,before.runId(),null,Duration.ofMinutes(5));
        });
        if(claim==null)return;
        try {
            var payload=runPayload(claim);var schedule=owned(payload.scheduleId(),claim.ownerUserId(),false);
            if(!users.current(claim.ownerUserId(),schedule.get("owner_username").toString()).supervisor())throw new SecurityException();
            String snapshot=write(snapshot(LocalDate.parse(payload.reportDate())));
            transactions.executeWithoutResult(status->{var owner=users.lockCurrent(claim.ownerUserId(),schedule.get("owner_username").toString());
                if(!owner.supervisor())throw new SecurityException();workflows.finishClaimJson(claim,"COMPLETED",payload,1,snapshot,sha(snapshot),null);});
        } catch(WorkflowConflictException stale) {
            log.debug("日报执行租约已变化，保留新执行者的状态");
        } catch(RuntimeException error) {
            String state=error instanceof SecurityException?"BLOCKED":"FAILED";
            try{transactions.executeWithoutResult(status->workflows.finishClaimJson(claim,state,runPayload(claim),null,null,null,state.equals("BLOCKED")?"AUTHORITY_REVOKED":"SNAPSHOT_UNAVAILABLE"));}
            catch(WorkflowConflictException stale){log.debug("日报失败回执已过期，保留新执行者的状态");}
        }
    }
    public ReportDocumentRenderer.File download(String runId,String format) {
        var caller=actor();return transactions.execute(status->{
            var fresh=users.lockCurrent(caller.userId(),caller.username());if(!fresh.supervisor())throw fail(403,"当前账号已无主管权限");
            var run=workflows.find(WorkflowKind.DIGEST_RUN,runId).orElseThrow(()->fail(404,"日报尚未完成或无访问权限"));
            if(run.ownerUserId()!=fresh.userId()||!"COMPLETED".equals(run.status())||run.resultJson()==null)throw fail(404,"日报尚未完成或无访问权限");
            var payload=runPayload(run);String snapshot=canonical(run.resultJson());
            if(!sha(snapshot).equals(run.resultSha256()))throw fail(409,"日报快照摘要不一致");
            String text=markdown(snapshot,run.resultSha256());ReportDocumentRenderer.File file="md".equals(format)?new ReportDocumentRenderer.File(text.getBytes(StandardCharsets.UTF_8),"text/markdown","md"):renderer.render(text,format);
            audit(payload.scheduleId(),fresh.userId(),"DOWNLOAD",0,new DigestAuditV1(null,null,runId,null,format,run.resultSha256()));return file;
        });
    }
    private void control() {
        jdbc.update("INSERT INTO runtime_state(namespace,owner_id,scope_key,revision) VALUES('DIGEST_CONTROL',0,'1',0) ON DUPLICATE KEY UPDATE owner_id=owner_id");
        jdbc.queryForObject("SELECT revision FROM runtime_state WHERE namespace='DIGEST_CONTROL' AND owner_id=0 AND scope_key='1' FOR UPDATE",Long.class);
    }
    private void quota(long owner) {
        var start=LocalDate.now(DISPLAY_ZONE).atStartOfDay(DISPLAY_ZONE).withZoneSameInstant(ZoneOffset.UTC).toLocalDateTime();
        if(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='DIGEST_RUN' AND owner_user_id=?",Long.class,owner)>=5000
            ||jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='DIGEST_RUN' AND owner_user_id=? AND created_at>=?",Long.class,owner,start)>=500)throw fail(429,"日报数量已达保留或当日上限，请先整理计划");
    }
    private void audit(String id,long user,String action,int version,DigestAuditV1 detail) {
        audits.append(new AuditEvent("DIGEST",user,user,"SCHEDULE",id,null,detail.runId(),null,null,action,(long)version,detail.snapshotSha256(),now(),1,detail));
    }

    private Map<String,Object> snapshot(LocalDate date){LocalDateTime from=date.atStartOfDay(DISPLAY_ZONE).withZoneSameInstant(taskZone).toLocalDateTime(),to=date.plusDays(1).atStartOfDay(DISPLAY_ZONE).withZoneSameInstant(taskZone).toLocalDateTime();var rows=rows("SELECT status,COUNT(*) AS taskCount,COALESCE(SUM(total_images),0) AS imageCount,COALESCE(SUM(successful_images),0) AS successfulImages,COALESCE(SUM(failed_images),0) AS failedImages,COALESCE(SUM(defect_count),0) AS modelDefectTargets,COALESCE(SUM(CASE WHEN review_status='PENDING' THEN 1 ELSE 0 END),0) AS pendingReviewCount,COALESCE(SUM(CASE WHEN review_status IS NULL THEN 1 ELSE 0 END),0) AS unrecordedReviewCount FROM detection_task WHERE created_at>=? AND created_at<? GROUP BY status ORDER BY status",from,to);return Map.of("reportDate",date.toString(),"timeZone",DISPLAY_ZONE.getId(),"taskStorageZone",taskZone.getId(),"basis","该日创建任务的当前状态快照；模型缺陷目标数不代表人工确认结果", "generatedAt",Instant.now().toString(),"statusGroups",rows);}
    private String markdown(String encoded,String hash){try{var root=json.readTree(encoded);var text=new StringBuilder("# 质检统计日报\n\n日期："+root.path("reportDate").asText()+"\n时区：Asia/Shanghai\n统计口径："+root.path("basis").asText()+"\n快照 SHA-256："+hash+"\n\n");for(var row:root.path("statusGroups")){text.append("## ").append(Map.of("COMPLETED","已完成","PARTIAL_FAILED","部分失败","FAILED","执行失败","RUNNING","检测中","UPLOADING","上传中","QUEUED","等待调度","DISPATCHING","派发中","CANCELLED","已取消").getOrDefault(row.path("status").asText(),row.path("status").asText())).append("\n");for(var item:Map.of("taskCount","任务数","imageCount","图片数","successfulImages","成功图片","failedImages","失败图片","modelDefectTargets","模型缺陷目标","pendingReviewCount","登记待复核","unrecordedReviewCount","未登记复核状态").entrySet())text.append(item.getValue()).append("：").append(row.path(item.getKey()).asLong()).append("\n");}if(root.path("statusGroups").isEmpty())text.append("该日暂无创建的检测任务\n");return text.append("\n本文件为统计快照，不替代人工复核、产品放行或报告审批。\n").toString();}catch(Exception error){throw fail(409,"日报快照无法读取");}}
    private String canonical(String encoded){try{return write(json.readValue(encoded,Object.class));}catch(Exception error){throw fail(409,"日报快照无法读取");}}
    private static CronExpression cron(String value){try{String text=value.strip();if(!text.split("\\s+")[0].equals("0"))throw new IllegalArgumentException();var cron=CronExpression.parse(text);next(cron);return cron;}catch(RuntimeException error){throw fail(400,"请使用六段 Cron，秒位固定为 0；例如每天 08:00：0 0 8 * * *");}}
    private static LocalDateTime next(CronExpression cron){var next=cron.next(ZonedDateTime.now(DISPLAY_ZONE));if(next==null)throw fail(400,"时间表达式没有后续执行时间");return next.withZoneSameInstant(ZoneOffset.UTC).toLocalDateTime();}
    private static LocalDateTime time(Object value){return value instanceof java.sql.Timestamp timestamp?timestamp.toLocalDateTime():(LocalDateTime)value;}
    private String write(Object value){try{return json.writeValueAsString(value);}catch(Exception error){throw new IllegalStateException("日报内容不能序列化");}}
    private static String sha(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(Exception error){throw new IllegalStateException(error);}}
    private static void requestId(String value){if(value==null||!value.matches("[A-Za-z0-9_-]{8,64}"))throw fail(400,"请求编号不正确");}
    private static BusinessException fail(int status,String message){return new BusinessException(status,message);}
}
