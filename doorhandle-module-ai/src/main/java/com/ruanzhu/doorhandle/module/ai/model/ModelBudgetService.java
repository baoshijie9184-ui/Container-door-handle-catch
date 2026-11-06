package com.ruanzhu.doorhandle.module.ai.model;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.framework.persistence.workflow.*;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.*;
import java.util.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.stereotype.Service;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

/** Account admission, permanent provider reports and observations; never a live provider balance. */
@Service
@ConditionalOnProperty(prefix="app.model-budget",name="enabled",havingValue="true")
@Transactional(rollbackFor=Exception.class,isolation=Isolation.READ_COMMITTED)
public class ModelBudgetService {
    public static class Exhausted extends RuntimeException { public Exhausted(String message){super(message);} }
    public record Ticket(long rootId,long attemptId,long owner,String modelId,String workflowId) { }
    public record Policy(String modelId,Long totalTokens,int warningPercent,OffsetDateTime expiresAt,long expectedVersion) { }
    public record Observation(String modelId,Long remainingTokens,OffsetDateTime observedAt,String sourceNote,String requestId) { }

    private final JdbcTemplate jdbc;
    private final BusinessUserDirectory users;
    private final ObjectMapper json;
    private final JdbcWorkflowStore workflows;
    private final JdbcAuditStore audits;
    private final QuotaAccountStore accounts;
    private final TransactionTemplate completion;

    public ModelBudgetService(JdbcTemplate jdbc,BusinessUserDirectory users,ObjectMapper json) {
        this.jdbc=jdbc;this.users=users;this.json=json;
        workflows=new JdbcWorkflowStore(jdbc,json,ModelBudgetWorkflow.protocols());
        audits=new JdbcAuditStore(jdbc,json,Map.of("MODEL_QUOTA_OBSERVATION",ModelBudgetWorkflow.ObservationV1.class));
        accounts=new QuotaAccountStore(jdbc);
        completion=new TransactionTemplate(new DataSourceTransactionManager(Objects.requireNonNull(jdbc.getDataSource())));
        completion.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
    }

    public List<Map<String,Object>> overview() {
        supervisor();
        var result=rows("""
                SELECT model_id,total_tokens,warning_percent,free_only,expires_at,version,updated_by,updated_at,
                    reserved_tokens,spent_tokens,unreconciled_legacy_attempts,
                    CASE WHEN unreconciled_legacy_attempts=0 THEN total_tokens-spent_tokens-reserved_tokens ELSE NULL END AS available_tokens,
                    total_tokens-spent_tokens-reserved_tokens AS remaining_upper_bound
                FROM llm_quota WHERE scope_type='MODEL' AND period_key='TOTAL' ORDER BY model_id LIMIT 300
                """);
        LocalDateTime now=workflows.now();
        for(var account:result) {
            String model=account.get("model_id").toString();
            var usage=row("""
                    SELECT COUNT(*) AS attempts,
                        COALESCE(SUM(CASE WHEN status<>'COMPLETED' THEN 1 ELSE 0 END),0) AS unknownAttempts,
                        COALESCE(SUM(CASE WHEN status='STARTED' THEN 1 ELSE 0 END),0) AS activeAttempts
                    FROM workflow_instance WHERE kind='LLM_PROVIDER_ATTEMPT'
                        AND resource_type='LLM_MODEL' AND resource_id=? COLLATE utf8mb4_0900_ai_ci
                    """,model);
            long spent=((Number)account.get("spent_tokens")).longValue();
            long legacyUnknown=((Number)account.get("unreconciled_legacy_attempts")).longValue();
            var legacy=row("""
                    SELECT COUNT(*) AS attempts,
                        COALESCE(SUM(CASE WHEN outcome='STARTED' THEN 1 ELSE 0 END),0) AS activeAttempts
                    FROM audit_event WHERE kind='LLM_LEGACY_ATTEMPT' AND legacy_attempt_model_id=?
                    """,model);
            usage.put("legacyAttempts",legacy.get("attempts"));
            usage.put("attempts",Math.addExact(((Number)usage.get("attempts")).longValue(),((Number)legacy.get("attempts")).longValue()));
            usage.put("activeAttempts",Math.addExact(((Number)usage.get("activeAttempts")).longValue(),((Number)legacy.get("activeAttempts")).longValue()));
            usage.put("unknownAttempts",Math.addExact(((Number)usage.get("unknownAttempts")).longValue(),legacyUnknown));
            usage.put("unreconciledLegacyAttempts",legacyUnknown);
            usage.put("reservedTokens",account.get("reserved_tokens"));
            usage.put("reportedTokens",spent);account.put("usage",usage);
            var latest=observationRows(model,1,true);
            account.put("providerObservation",latest.isEmpty()?null:latest.get(0));
            String alert="UNCONFIGURED";Long limit=number(account.get("total_tokens"));
            long unknown=((Number)usage.get("unknownAttempts")).longValue();
            int warning=((Number)account.get("warning_percent")).intValue();
            double committedOrReserved=(double)spent+((Number)account.get("reserved_tokens")).longValue();
            if(limit!=null)alert=unknown>0?"USAGE_INCOMPLETE":committedOrReserved>=limit?"LOCAL_LIMIT_REACHED"
                    :committedOrReserved*100>=limit*(double)warning?"LOCAL_WARNING":"LOCAL_NORMAL";
            Long remaining=latest.isEmpty()?null:number(latest.get(0).get("remaining_tokens"));
            if(remaining!=null&&limit!=null&&remaining*100.0<=limit*(100-warning))alert="LAST_OBSERVATION_WARNING";
            if(remaining!=null&&remaining==0)alert="LAST_OBSERVATION_EXHAUSTED";
            if(legacyUnknown>0)alert="USAGE_INCOMPLETE";
            LocalDateTime expiry=date(account.get("expires_at"));
            if(expiry!=null&&!expiry.isAfter(now))alert="EXPIRED";
            account.put("alert",alert);account.put("liveProviderRemaining",null);
            account.put("coverage","已接入的 AgentScope 模型路由及已导入的旧额度记录；不含独立记忆、独立 RAG、探测和站外调用");
        }
        return result;
    }

    public void policy(Policy request) {
        var actor=lockedSupervisor();validate(request.modelId());
        if(request.totalTokens()!=null&&(request.totalTokens()<0||request.totalTokens()>1_000_000_000_000L)
                ||request.warningPercent()<1||request.warningPercent()>100||request.expectedVersion()<0)
            throw new BusinessException(400,"额度参数不正确");
        LocalDateTime expiry=request.expiresAt()==null?null:request.expiresAt().withOffsetSameInstant(ZoneOffset.UTC).toLocalDateTime();
        var payload=new ModelBudgetWorkflow.ChangeV1(request.totalTokens(),request.warningPercent(),expiry);
        String command=UUID.randomUUID().toString(),digest=sha(write(request));
        var receipt=workflows.create(new WorkflowDraft(command,WorkflowKind.LLM_QUOTA_CHANGE,
                JdbcWorkflowStore.ownerScope(actor.userId()),command,digest,actor.userId(),actor.userId(),null,
                "LLM_MODEL",request.modelId(),null,null,null,"COMPLETED",null,1,payload));
        var before=accounts.lockModel(request.modelId());
        if(request.expectedVersion()!=before.version()&&!(request.expectedVersion()==0&&before.version()==1))
            throw new BusinessException(409,"额度配置已更新，请重新读取");
        long version=Math.addExact(before.version(),1);
        if(jdbc.update("""
                UPDATE llm_quota SET total_tokens=?,warning_percent=?,expires_at=?,free_only=TRUE,
                    version=?,updated_by=?,updated_at=UTC_TIMESTAMP(6) WHERE id=? AND version=?
                """,request.totalTokens(),request.warningPercent(),expiry,version,actor.userId(),before.id(),before.version())!=1)
            throw new IllegalStateException("Concurrent quota policy change");
        jdbc.update("UPDATE workflow_instance SET resource_revision=? WHERE id=?",version,receipt.id());
        jdbc.update("""
                INSERT INTO llm_usage(account_id,root_operation_id,operation_id,entry_key,entry_type,
                    reserved_delta,spent_delta,limit_before,limit_after,request_sha256,actor_user_id,created_at)
                VALUES(?,?,?,'POLICY','LIMIT_CHANGE',0,0,?,?,?,?,UTC_TIMESTAMP(6))
                """,before.id(),receipt.id(),receipt.id(),before.limit(),request.totalTokens(),digest,actor.userId());
    }

    public void observe(Observation request) {
        var actor=lockedSupervisor();validate(request.modelId());
        if(request.remainingTokens()==null||request.remainingTokens()<0||request.remainingTokens()>1_000_000_000_000L
                ||request.observedAt()==null||request.observedAt().toInstant().isAfter(Instant.now().plusSeconds(60))
                ||request.sourceNote()==null||request.sourceNote().isBlank()||request.sourceNote().length()>500
                ||request.requestId()==null||!request.requestId().matches("[A-Za-z0-9_-]{8,64}"))
            throw new BusinessException(400,"供应商核对记录不正确");
        accounts.lockModel(request.modelId());String digest=sha(write(request));
        if(repeatedObservation(actor.userId(),request.requestId(),digest))return;
        try {
            audits.appendObservation(new AuditEvent("MODEL_QUOTA_OBSERVATION",actor.userId(),actor.userId(),
                    "LLM_MODEL",request.modelId(),null,null,null,request.requestId(),"OBSERVATION",null,digest,null,
                    1,new ModelBudgetWorkflow.ObservationV1(request.sourceNote().strip())),request.remainingTokens(),
                    request.observedAt().withOffsetSameInstant(ZoneOffset.UTC).toLocalDateTime());
        } catch(DuplicateKeyException duplicate) {
            // The identity spans models; locking only this MODEL account cannot serialize its competing writer.
            // Resolve the intended immutable receipt only. Other unique-key errors remain storage failures.
            if(!repeatedObservation(actor.userId(),request.requestId(),digest))throw duplicate;
        }
    }

    private boolean repeatedObservation(long actor,String request,String digest) {
        var previous=rows("""
                SELECT content_sha256 FROM audit_event WHERE kind='MODEL_QUOTA_OBSERVATION'
                    AND request_scope=? AND observation_request_id=? FOR SHARE
                """,JdbcWorkflowStore.ownerScope(actor),request);
        if(previous.isEmpty())return false;
        if(previous.size()!=1||!digest.equals(previous.get(0).get("content_sha256")))
            throw new BusinessException(409,"请求编号已用于其他核对记录");
        return true;
    }

    public List<Map<String,Object>> observations(String id) {
        supervisor();validate(id);return observationRows(id,100,false);
    }

    /** Returning a ticket is a one-time dispatch authorization, never a replay instruction. */
    public Ticket started(ModelBudgetContext context,String requestId,String attemptId,String modelId,long reservedTokens,String basis) {
        try {
            Objects.requireNonNull(context);validate(modelId);
            var actor=users.lockCurrent(context.actor().userId(),context.actor().username());
            var requestPayload=new ModelBudgetWorkflow.RequestV1(context.runId());
            var root=workflows.create(new WorkflowDraft(UUID.randomUUID().toString(),WorkflowKind.LLM_REQUEST,
                    JdbcWorkflowStore.ownerScope(actor.userId()),requestId,sha(write(requestPayload)),actor.userId(),actor.userId(),null,
                    "LLM_REQUEST",requestId,null,null,context.runId(),"OPEN",null,1,requestPayload));
            root=workflows.findLocked(WorkflowKind.LLM_REQUEST,root.workflowId()).orElseThrow();
            if(!Set.of("OPEN","NEEDS_REVIEW").contains(root.status())||root.ownerUserId()!=actor.userId()
                    ||!Objects.equals(root.runId(),context.runId()))throw new ModelAttemptTrace.RecordingException();
            var payload=new ModelBudgetWorkflow.AttemptV1(modelId,reservedTokens,basis);
            var attempt=workflows.create(new WorkflowDraft(attemptId,WorkflowKind.LLM_PROVIDER_ATTEMPT,
                    "LLM_REQUEST:"+root.id(),attemptId,sha(write(payload)),actor.userId(),actor.userId(),root.id(),
                    "LLM_MODEL",modelId,null,null,context.runId(),"RESERVED",null,1,payload));
            attempt=workflows.findLocked(WorkflowKind.LLM_PROVIDER_ATTEMPT,attempt.workflowId()).orElseThrow();
            if(!"RESERVED".equals(attempt.status()))throw new ModelAttemptTrace.RecordingException();
            var reservation=accounts.reserve(root.id(),attempt.id(),actor.userId(),modelId,reservedTokens);
            if(!reservation.created())throw new ModelAttemptTrace.RecordingException();
            // MODEL locking serializes a supervisor's new observation with this admission.
            var latest=observationRows(modelId,1,true);
            if(!latest.isEmpty()&&number(latest.get(0).get("remaining_tokens"))==0)
                throw new Exhausted("该模型最近核对的免费额度已耗尽，请先核对供应商额度");
            workflows.transition(attempt,"STARTED",payload,context.runId(),null,null);
            return new Ticket(root.id(),attempt.id(),actor.userId(),modelId,attempt.workflowId());
        } catch(Exhausted exhausted) { throw exhausted; }
        catch(RuntimeException failed) { throw new ModelAttemptTrace.RecordingException(); }
    }

    /** A logout does not invalidate accounting. Commit failures are inside the recording-error boundary. */
    @Transactional(propagation=Propagation.NOT_SUPPORTED)
    public void finished(Ticket ticket,Map<String,Object> fields) {
        try { completion.executeWithoutResult(status->complete(ticket,fields)); }
        catch(RuntimeException failed) { throw new ModelAttemptTrace.RecordingException(); }
    }

    private void complete(Ticket ticket,Map<String,Object> fields) {
        Objects.requireNonNull(ticket);Objects.requireNonNull(fields);validate(ticket.modelId());
        if(!ticket.modelId().equals(fields.get("modelId")))throw new IllegalStateException("Provider report model changed");
        // Owner-before-workflow ordering matches admission and personal-account FK checks.
        if(jdbc.queryForList("SELECT id FROM users WHERE id=? FOR SHARE",Long.class,ticket.owner()).size()!=1)
            throw new IllegalStateException("Model accounting owner disappeared");
        var rootRows=rows("SELECT workflow_id FROM workflow_instance WHERE id=? AND kind='LLM_REQUEST' FOR UPDATE",ticket.rootId());
        if(rootRows.size()!=1)throw new IllegalStateException("Model request disappeared");
        var root=workflows.findLocked(WorkflowKind.LLM_REQUEST,rootRows.get(0).get("workflow_id").toString()).orElseThrow();
        var attempt=workflows.findLocked(WorkflowKind.LLM_PROVIDER_ATTEMPT,ticket.workflowId()).orElseThrow();
        if(root.ownerUserId()!=ticket.owner()||attempt.ownerUserId()!=ticket.owner()||attempt.id()!=ticket.attemptId()
                ||!Objects.equals(attempt.parentWorkflowId(),ticket.rootId())||!ticket.modelId().equals(attempt.resourceId()))
            throw new IllegalStateException("Provider report identity changed");
        String outcome=Objects.toString(fields.get("status"),"FAILED");
        if(!Set.of("COMPLETED","FAILED","CANCELLED").contains(outcome))throw new IllegalArgumentException("Invalid provider report status");
        Long input=number(fields.get("inputTokens")),output=number(fields.get("outputTokens")),cached=number(fields.get("cachedTokens"));
        if(cached!=null&&input!=null&&cached>input)throw new IllegalArgumentException("Cached tokens exceed input tokens");
        var report=new ModelBudgetWorkflow.ReportV1(outcome,input,output,cached);
        String body=write(report),digest=sha(body);
        if(attempt.resultJson()!=null) {
            if(!digest.equals(attempt.resultSha256())||!digest.equals(sha(attempt.resultJson())))
                throw new IllegalStateException("Provider report conflicts with its permanent receipt");
            return;
        }
        if(!Set.of("STARTED","NEEDS_REVIEW").contains(attempt.status()))
            throw new IllegalStateException("Provider attempt was not dispatched");
        boolean settled="COMPLETED".equals(outcome)&&input!=null&&output!=null;
        if(settled)accounts.settle(ticket.rootId(),ticket.attemptId(),ticket.owner(),ticket.modelId(),input,output,cached);
        String state=settled?"COMPLETED":"NEEDS_REVIEW";
        var payload=workflows.payload(attempt,ModelBudgetWorkflow.AttemptV1.class);
        if(!state.equals(attempt.status()))attempt=workflows.transition(attempt,state,payload,attempt.runId(),null,null);
        if(jdbc.update("""
                UPDATE workflow_instance SET result_version=1,result_json=?,result_sha256=?,revision=revision+1,
                    updated_at=UTC_TIMESTAMP(6) WHERE id=? AND revision=? AND result_json IS NULL AND status=?
                """,body,digest,attempt.id(),attempt.revision(),state)!=1)
            throw new IllegalStateException("Provider report receipt changed concurrently");
        long unresolved=jdbc.queryForObject("""
                SELECT COUNT(*) FROM workflow_instance WHERE parent_workflow_id=? AND kind='LLM_PROVIDER_ATTEMPT'
                    AND status NOT IN ('COMPLETED','FAILED','CANCELLED')
                """,Long.class,root.id());
        String rootState=unresolved==0?"COMPLETED":"NEEDS_REVIEW";
        if(!rootState.equals(root.status()))workflows.transition(root,rootState,
                workflows.payload(root,ModelBudgetWorkflow.RequestV1.class),root.runId(),null,null);
    }

    private List<Map<String,Object>> observationRows(String model,int limit,boolean includeId) {
        return rows("SELECT "+(includeId?"id,":"")+"quantity AS remaining_tokens,observed_at,"
                +"JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.sourceNote')) AS source_note,actor_user_id,occurred_at AS created_at "
                +"FROM audit_event WHERE kind='MODEL_QUOTA_OBSERVATION' AND observation_model_id=? "
                +"ORDER BY observed_at DESC,id DESC LIMIT ?",model,limit);
    }
    private BusinessUserDirectory.Identity supervisor() {
        var actor=users.authenticated();actor=users.current(actor.userId(),actor.username());
        if(!actor.supervisor())throw new BusinessException(403,"仅主管可管理模型额度");return actor;
    }
    private BusinessUserDirectory.Identity lockedSupervisor() {
        var actor=supervisor();actor=users.lockCurrent(actor.userId(),actor.username());
        if(!actor.supervisor())throw new BusinessException(403,"当前账号已无主管权限");return actor;
    }
    private static void validate(String model) {
        try { ModelBudgetWorkflow.model(model); }
        catch(IllegalArgumentException invalid) { throw new BusinessException(400,"模型标识格式不正确"); }
    }
    private List<Map<String,Object>> rows(String sql,Object... arguments) {
        return jdbc.query(sql,com.ruanzhu.doorhandle.common.LocalDateTimeRow::read,arguments);
    }
    private Map<String,Object> row(String sql,Object... arguments) {
        var values=rows(sql,arguments);if(values.size()!=1)throw new IllegalStateException("数据记录未完整读取");return values.get(0);
    }
    private static LocalDateTime date(Object value) {
        if(value==null)return null;
        if(value instanceof LocalDateTime time)return time;
        throw new IllegalStateException("Expected UTC database local date-time");
    }
    private static Long number(Object value) {
        if(value==null)return null;
        if(!(value instanceof Number number))throw new IllegalArgumentException("Invalid token quantity");
        long result=new BigDecimal(number.toString()).longValueExact();
        if(result<0)throw new IllegalArgumentException("Negative token quantity");return result;
    }
    private String write(Object value) {
        try{return json.writeValueAsString(value);}catch(Exception error){throw new IllegalStateException("Cannot encode model accounting receipt",error);}
    }
    private static String sha(String value) {
        try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}
        catch(Exception error){throw new IllegalStateException(error);}
    }
}
