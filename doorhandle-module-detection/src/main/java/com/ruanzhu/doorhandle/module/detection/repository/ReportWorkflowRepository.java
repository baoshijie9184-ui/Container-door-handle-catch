package com.ruanzhu.doorhandle.module.detection.repository;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.JdbcTransactions;
import com.ruanzhu.doorhandle.framework.persistence.workflow.*;
import com.ruanzhu.doorhandle.module.detection.dto.report.QualityReportDtos.*;
import com.ruanzhu.doorhandle.module.detection.dto.report.ReportTime;
import com.ruanzhu.doorhandle.module.detection.repository.ReportWorkflowProtocols.*;
import org.springframework.jdbc.core.JdbcTemplate;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.*;

/** Durable report commands, approval confirmations, origins and audit, in the caller's transaction. */
public final class ReportWorkflowRepository {
    public static final String RESOURCE="QUALITY_REPORT";
    public static final String CONFIRMATION_SCOPE="REPORT_CONFIRMATION", DELIVERY_SCOPE="REPORT_DELIVERY", CONSUMPTION_SCOPE="REPORT_CONSUMPTION";
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final JdbcWorkflowStore workflows;
    private final JdbcAuditStore audits;

    public ReportWorkflowRepository(JdbcTemplate jdbc,ObjectMapper json) {
        this.jdbc=jdbc;this.json=json;this.workflows=new JdbcWorkflowStore(jdbc,json,ReportWorkflowProtocols.protocols());
        this.audits=new JdbcAuditStore(jdbc,json,Map.of(RESOURCE,AuditV1.class));
    }
    public JdbcWorkflowStore workflows(){return workflows;}
    public Optional<WorkflowRecord> command(long actor,String request){return workflows.findByRequest(WorkflowKind.REPORT_COMMAND,JdbcWorkflowStore.ownerScope(actor),request);}
    public CommandV1 commandPayload(WorkflowRecord row){return workflows.payload(row,CommandV1.class);}
    public void saveCommand(long actor,String request,String digest,QualityReportRepository.Row report,String responseJson) {
        workflows.create(draft(WorkflowKind.REPORT_COMMAND,JdbcWorkflowStore.ownerScope(actor),request,digest,report.ownerUserId(),actor,
                report.reportId(),report.version(),null,"COMPLETED",null,new CommandV1(responseJson)));
    }
    public LocalDateTime confirmation(long actor,QualityReportRepository.Row report,String token,String decisionSha) {
        Long pending=jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='REPORT_CONFIRMATION' AND resource_type='QUALITY_REPORT' AND resource_id=? AND actor_user_id=? AND status='PENDING' AND expires_at>UTC_TIMESTAMP(6)",Long.class,report.reportId(),actor);
        if(pending>=20)throw new com.ruanzhu.doorhandle.common.BusinessException(429,"确认预览过多，请稍后重试");
        LocalDateTime expires=workflows.now().plusMinutes(10);
        var payload=new ConfirmationV1(report.snapshotSha256(),decisionSha);
        workflows.create(draft(WorkflowKind.REPORT_CONFIRMATION,CONFIRMATION_SCOPE,token,sha(report.snapshotSha256()+":"+decisionSha),report.ownerUserId(),actor,
                report.reportId(),report.version(),null,"PENDING",expires,payload));
        return expires;
    }
    public WorkflowRecord requireConfirmation(long actor,QualityReportRepository.Row report,String token,String decisionSha) {
        if(token==null||!token.matches("[a-f0-9]{64}"))throw new com.ruanzhu.doorhandle.common.BusinessException(409,"请重新预览审批操作");
        var row=workflows.findByRequest(WorkflowKind.REPORT_CONFIRMATION,CONFIRMATION_SCOPE,token)
                .orElseThrow(()->new com.ruanzhu.doorhandle.common.BusinessException(409,"请重新预览审批操作"));
        var body=workflows.payload(row,ConfirmationV1.class);
        if(!Objects.equals(row.actorUserId(),actor)||!report.reportId().equals(row.resourceId())||!Objects.equals(row.resourceRevision(),(long)report.version())
                ||!"PENDING".equals(row.status())||!report.snapshotSha256().equals(body.snapshotSha256())||!decisionSha.equals(body.decisionSha256()))
            throw new com.ruanzhu.doorhandle.common.BusinessException(409,"审批确认与当前内容不一致，请重新预览");
        if(row.expiresAt()==null||!row.expiresAt().isAfter(workflows.now()))throw new com.ruanzhu.doorhandle.common.BusinessException(409,"审批确认已过期，请重新预览");
        return row;
    }
    public void consumeConfirmation(WorkflowRecord row) {
        // A DB deadline predicate prevents accepting a token that expires after the preview check.
        JdbcTransactions.requireActive(jdbc);
        if(jdbc.update("UPDATE workflow_instance SET status='USED',revision=revision+1,updated_at=UTC_TIMESTAMP(6),finished_at=UTC_TIMESTAMP(6) WHERE id=? AND kind='REPORT_CONFIRMATION' AND status='PENDING' AND revision=? AND fence=? AND claim_token IS NULL AND expires_at>UTC_TIMESTAMP(6)",row.id(),row.revision(),row.fence())!=1)
            throw new com.ruanzhu.doorhandle.common.BusinessException(409,"审批确认已过期或已使用，请重新预览");
    }
    public void enqueue(QualityReportRepository.Row report,long actor,String eventId,String eventType,String eventJson) {
        var row=workflows.create(draft(WorkflowKind.REPORT_DELIVERY,DELIVERY_SCOPE,eventId,sha(eventJson),report.ownerUserId(),actor,
                report.reportId(),report.version(),null,"PENDING",null,new DeliveryV1(eventType,eventJson)));
        jdbc.update("UPDATE workflow_instance SET next_attempt_at=created_at WHERE id=? AND kind='REPORT_DELIVERY' AND next_attempt_at IS NULL",row.id());
    }
    public List<EventDelivery> events(String reportId) {
        return jdbc.query("""
                SELECT e.*,r.finished_at AS consumed_at FROM workflow_instance e LEFT JOIN workflow_instance r
                  ON r.kind='REPORT_CONSUMPTION' AND r.idempotency_scope='REPORT_CONSUMPTION' AND r.report_request_id=e.report_request_id
                WHERE e.kind='REPORT_DELIVERY' AND e.resource_type='QUALITY_REPORT' AND e.resource_id=? ORDER BY e.created_at,e.request_id LIMIT 100
                """,(r,n)->{
            var body=decode(r.getString("payload_json"),DeliveryV1.class);
            return new EventDelivery(r.getString("request_id"),body.eventType(),r.getString("status"),r.getInt("attempts"),ReportTime.fromUtc(r.getObject("next_attempt_at",LocalDateTime.class)),ReportTime.fromUtc(r.getObject("finished_at",LocalDateTime.class)),r.getString("error_code"),ReportTime.fromUtc(r.getObject("consumed_at",LocalDateTime.class)));
        },reportId);
    }
    public boolean retry(String report,String event,int attempts) {
        JdbcTransactions.requireActive(jdbc);
        return jdbc.update("UPDATE workflow_instance SET status='RETRY',revision=revision+1,next_attempt_at=UTC_TIMESTAMP(6),updated_at=UTC_TIMESTAMP(6),error_code=NULL WHERE kind='REPORT_DELIVERY' AND resource_type='QUALITY_REPORT' AND resource_id=? AND report_request_id=? AND status IN ('FAILED','RETRY') AND attempts=? AND claim_token IS NULL",report,event,attempts)==1;
    }
    public void audit(QualityReportRepository.Row report,long actor,String username,String action,String before,String reason) {
        audits.append(new AuditEvent(RESOURCE,report.ownerUserId(),actor,RESOURCE,report.reportId(),null,null,null,null,action,(long)report.version(),report.snapshotSha256(),null,1,new AuditV1(username,before,report.status(),reason)));
    }
    public List<Audit> audit(String report) {
        return jdbc.query("""
                SELECT a.*,o.run_id AS origin_run,o.payload_json AS origin_payload FROM audit_event a
                LEFT JOIN workflow_instance o ON o.kind='REPORT_AGENT_ORIGIN' AND o.resource_type='QUALITY_REPORT'
                  AND o.resource_id=a.resource_id AND o.resource_revision=a.revision AND o.actor_user_id=a.actor_user_id AND a.action IN ('CREATE','EDIT')
                WHERE a.kind='QUALITY_REPORT' AND a.resource_type='QUALITY_REPORT' AND a.resource_id=? ORDER BY a.id DESC LIMIT 100
                """,(r,n)->{
            if(r.getInt("payload_version")!=1)throw new IllegalStateException("Unsupported report audit payload");
            var body=decode(r.getString("payload_json"),AuditV1.class);
            var origin=r.getString("origin_payload")==null?null:decode(r.getString("origin_payload"),AgentOriginV1.class);
            return new Audit(r.getLong("id"),body.actorUsername(),r.getString("action"),body.beforeStatus(),body.afterStatus(),r.getInt("revision"),body.reason(),r.getString("content_sha256"),ReportTime.fromUtc(r.getObject("occurred_at",LocalDateTime.class)),r.getString("origin_run"),origin==null?null:origin.callId(),origin==null?null:origin.toolName());
        },report);
    }
    public void origin(long actor,String request,String report,int version,long owner,String run,String call,String tool) {
        var payload=new AgentOriginV1(call,tool);
        // A tool retry can have a new call ID; its first recorded origin remains immutable.
        String digest=sha(actor+"|"+report+"|"+version+"|"+run.length()+":"+run+"|"+tool);
        workflows.create(draft(WorkflowKind.REPORT_AGENT_ORIGIN,JdbcWorkflowStore.ownerScope(actor),request,digest,owner,actor,report,version,run,"COMPLETED",null,payload));
    }
    public Optional<WorkflowRecord> origin(long actor,String run,String call,String tool) {
        var ids=jdbc.queryForList("""
                SELECT workflow_id FROM workflow_instance WHERE kind='REPORT_AGENT_ORIGIN' AND actor_user_id=?
                  AND run_id COLLATE utf8mb4_unicode_ci=?
                  AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.callId')) COLLATE utf8mb4_unicode_ci=?
                  AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.toolName')) COLLATE utf8mb4_unicode_ci=? ORDER BY id LIMIT 1
                """,String.class,actor,run,call,tool);
        return ids.isEmpty()?Optional.empty():workflows.find(WorkflowKind.REPORT_AGENT_ORIGIN,ids.get(0));
    }
    public static WorkflowDraft draft(WorkflowKind kind,String scope,String request,String digest,long owner,long actor,String report,long version,String run,String state,LocalDateTime expires,Object payload) {
        if(report==null||!report.matches("qr-[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")||version<1)throw new IllegalArgumentException("Invalid report workflow resource");
        return new WorkflowDraft(UUID.randomUUID().toString(),kind,scope,request,digest,owner,actor,null,RESOURCE,report,version,null,run,state,expires,1,payload);
    }
    public String encode(Object value){try{return json.writeValueAsString(value);}catch(Exception error){throw new IllegalArgumentException("Cannot encode report workflow",error);}}
    public <T>T decode(String value,Class<T> type){try{return json.readValue(value,type);}catch(Exception error){throw new IllegalStateException("Invalid persisted report payload",error);}}
    public static String sha(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(Exception error){throw new IllegalStateException(error);}}
}
