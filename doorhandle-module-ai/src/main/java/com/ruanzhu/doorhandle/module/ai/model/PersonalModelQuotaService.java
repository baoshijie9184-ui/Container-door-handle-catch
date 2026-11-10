package com.ruanzhu.doorhandle.module.ai.model;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.annotation.JsonDeserialize;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.framework.persistence.workflow.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
@ConditionalOnProperty(prefix="app.model-budget",name="enabled",havingValue="true")
@Transactional(rollbackFor=Exception.class,isolation=Isolation.READ_COMMITTED)
public class PersonalModelQuotaService {
    public record Apply(String modelId,@JsonDeserialize(using=ExactInteger.class)Long requestedTokens,String reason,String requestId) { }
    public record Decision(String decision,String reason,@JsonDeserialize(using=ExactInteger.class)Long expectedVersion,String requestId) { }
    public record Cancel(@JsonDeserialize(using=ExactInteger.class)Long expectedVersion,String requestId) { }
    /** Quota amounts and revisions must not silently truncate JSON fractions or coerce strings. */
    public static final class ExactInteger extends com.fasterxml.jackson.databind.JsonDeserializer<Long> {
        @Override public Long deserialize(com.fasterxml.jackson.core.JsonParser parser,com.fasterxml.jackson.databind.DeserializationContext context)throws java.io.IOException {
            if(!parser.hasToken(com.fasterxml.jackson.core.JsonToken.VALUE_NUMBER_INT))
                return context.reportInputMismatch(Long.class,"额度与版本须为 JSON 整数");
            return parser.getLongValue();
        }
    }
    public record MineModel(String modelId,String provider,String model,boolean configured,boolean hasPersonalQuota,
            Long totalTokens,long reservedTokens,long spentTokens,Long availableTokens,OffsetDateTime expiresAt,Long version,
            String enterpriseBlockedReason) { }
    public record Application(String id,long cursor,String modelId,long applicantUserId,long requestedTokens,String reason,
            String status,long version,OffsetDateTime createdAt,OffsetDateTime updatedAt,OffsetDateTime finishedAt,
            Long deciderUserId,String decisionReason) { }
    public record Page(List<Application> items,Long nextCursor) { }
    private record Stored(long cursor,String id,long owner,String model,long requestedTokens,String requestHash,
            String status,long version,String payload,String result,Integer resultVersion,String resultHash,Long decider,
            LocalDateTime created,LocalDateTime updated,LocalDateTime finished) { }
    private record Personal(long id,Long total,long reserved,long spent,long version,LocalDateTime expires) { }
    private static final Set<String> STATES=Set.of("PENDING","APPROVED","REJECTED","CANCELLED");
    private final JdbcTemplate jdbc;
    private final BusinessUserDirectory users;
    private final AgentModelService models;
    private final ObjectMapper json;
    private final JdbcAuditStore audits;
    private final QuotaAccountStore accounts;
    private final WorkflowProtocol<PersonalModelQuotaWorkflow.ApplicationV1> protocol=PersonalModelQuotaWorkflow.protocol();

    public PersonalModelQuotaService(JdbcTemplate jdbc,BusinessUserDirectory users,AgentModelService models,ObjectMapper json) {
        this.jdbc=jdbc;this.users=users;this.models=models;
        this.json=json.copy().enable(DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES)
                .enable(DeserializationFeature.FAIL_ON_NULL_FOR_PRIMITIVES);
        audits=new JdbcAuditStore(jdbc,this.json,Map.of("LLM_QUOTA_APPLICATION",PersonalModelQuotaWorkflow.AuditV1.class));
        accounts=new QuotaAccountStore(jdbc);
    }

    public List<MineModel> mine() {
        var actor=current();var result=new ArrayList<MineModel>();
        for(var model:models.entries()) {
            var personal=personal(actor.userId(),model.id(),false);
            result.add(new MineModel(model.id(),model.provider(),model.model(),model.configured(),personal!=null,
                    personal==null?null:personal.total(),personal==null?0:personal.reserved(),personal==null?0:personal.spent(),
                    personal==null||personal.total()==null?null:Math.subtractExact(Math.subtractExact(personal.total(),personal.spent()),personal.reserved()),
                    personal==null?null:utc(personal.expires()),personal==null?null:personal.version(),enterpriseBlockedReason(model.id())));
        }
        return List.copyOf(result);
    }

    public Page applications(String scope,String status,long before,int limit) {
        var actor=current();
        if(!Set.of("mine","team").contains(scope)||before<1||limit<1||limit>100||status!=null&&!STATES.contains(status))
            throw bad("申请分页参数不正确");
        if("team".equals(scope)&&!actor.supervisor())throw forbidden();
        String sql="SELECT * FROM workflow_instance WHERE kind='LLM_QUOTA_APPLICATION' AND id<?";
        var args=new ArrayList<Object>();args.add(before);
        if("mine".equals(scope)){sql+=" AND owner_user_id=?";args.add(actor.userId());}
        if(status!=null){sql+=" AND status=?";args.add(status);}
        args.add(limit+1);
        var records=jdbc.query(sql+" ORDER BY id DESC LIMIT ?",this::stored,args.toArray());
        boolean more=records.size()>limit;
        var items=records.stream().limit(limit).map(this::view).toList();
        return new Page(items,more?items.get(items.size()-1).cursor():null);
    }

    public Application apply(Apply request) {
        Objects.requireNonNull(request);validateModel(request.modelId());requestId(request.requestId());
        if(request.requestedTokens()==null||request.requestedTokens()<1||request.requestedTokens()>1_000_000_000_000L)
            throw bad("申请额度须为 1 到 1000000000000 的整数");
        String reason=reason(request.reason());var actor=lockParticipants(current(),null);
        var payload=new PersonalModelQuotaWorkflow.ApplicationV1(reason);
        protocol.requireInitial("PENDING");protocol.validatePayload(payload,1);
        String hash=sha(write(new PersonalModelQuotaWorkflow.ApplicationDigest("APPLY",request.modelId(),request.requestedTokens(),reason)));
        var previous=jdbc.query("SELECT * FROM workflow_instance WHERE kind='LLM_QUOTA_APPLICATION' AND idempotency_scope=? AND request_id=? FOR UPDATE",
                this::stored,JdbcWorkflowStore.ownerScope(actor.userId()),request.requestId());
        if(!previous.isEmpty()) {
            var existing=previous.get(0);
            if(!existing.requestHash().equals(hash))throw conflict();
            if(!receipt(actor.userId(),request.requestId(),existing.id(),"APPLY",hash))throw inconsistent();
            return view(existing);
        }
        String id=UUID.randomUUID().toString();
        if(receipt(actor.userId(),request.requestId(),id,"APPLY",hash))throw inconsistent();
        jdbc.update("""
                INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,
                    owner_user_id,actor_user_id,resource_type,resource_id,requested_tokens,status,payload_version,payload_json)
                VALUES(?,'LLM_QUOTA_APPLICATION',?,?,?,?,?,'LLM_MODEL',?,?,'PENDING',1,?)
                """,id,JdbcWorkflowStore.ownerScope(actor.userId()),request.requestId(),hash,actor.userId(),actor.userId(),
                request.modelId(),request.requestedTokens(),write(payload));
        var application=locked(id);
        requireConfigured(request.modelId());accounts.lockModel(request.modelId());
        var account=personal(actor.userId(),request.modelId(),true);
        if(account!=null&&account.total()==null)throw new BusinessException(409,"已有个人无限额配置，无需重复申请");
        audit(application,actor.userId(),request.requestId(),"APPLY","PENDING",hash,reason,0);
        return view(application);
    }

    public Application decide(String id,Decision request) {
        Objects.requireNonNull(request);identity(id);requestId(request.requestId());version(request.expectedVersion());
        if(!Set.of("APPROVE","REJECT").contains(Objects.toString(request.decision(),"")))throw bad("审批结果不正确");
        String reason=reason(request.reason());var actor=current();if(!actor.supervisor())throw forbidden();
        long owner=owner(id);actor=lockParticipants(actor,owner);if(!actor.supervisor())throw forbidden();
        var application=locked(id);if(application.owner()!=owner)throw inconsistent();
        if(application.owner()==actor.userId())throw new BusinessException(403,"不能审批本人提交的额度申请，请由其他主管处理");
        return finish(application,actor,request.decision(),reason,request.expectedVersion(),request.requestId());
    }

    public Application cancel(String id,Cancel request) {
        Objects.requireNonNull(request);identity(id);requestId(request.requestId());version(request.expectedVersion());
        var actor=current();if(owner(id)!=actor.userId())throw forbidden();
        actor=lockParticipants(actor,actor.userId());var application=locked(id);
        if(application.owner()!=actor.userId())throw forbidden();
        return finish(application,actor,"CANCEL",null,request.expectedVersion(),request.requestId());
    }

    private Application finish(Stored application,BusinessUserDirectory.Identity actor,String action,String reason,long expectedVersion,String requestId) {
        String hash=sha(write(new PersonalModelQuotaWorkflow.DecisionDigest(action,application.id(),expectedVersion,reason)));
        boolean repeated=receipt(actor.userId(),requestId,application.id(),action,hash);
        if(!"PENDING".equals(application.status())) {
            var result=decision(application);
            if(!repeated||result.actorUserId()!=actor.userId()||!requestId.equals(result.requestId())||!hash.equals(result.requestSha256()))throw conflict();
            return view(application);
        }
        if(repeated)throw inconsistent();
        if(application.version()!=expectedVersion)throw conflict();
        String next=switch(action){case "APPROVE"->"APPROVED";case "REJECT"->"REJECTED";case "CANCEL"->"CANCELLED";default->throw bad("审批结果不正确");};
        protocol.requireTransition(application.status(),next);
        Long before=null,after=null;
        if("APPROVE".equals(action)) {
            requireConfigured(application.model());accounts.lockModel(application.model());
            var personal=personal(application.owner(),application.model(),true);
            if(personal!=null&&personal.total()==null)throw new BusinessException(409,"该成员已有个人无限额配置");
            before=personal==null?null:personal.total();
            try{after=Math.addExact(personal==null?0:personal.total(),application.requestedTokens());}
            catch(ArithmeticException overflow){throw new BusinessException(409,"个人额度累计超出支持范围");}
            if(personal==null) {
                jdbc.update("""
                        INSERT INTO llm_quota(scope_type,owner_user_id,model_id,period_key,total_tokens,updated_by,created_at,updated_at)
                        VALUES('USER',?,?,'TOTAL',?,?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))
                        """,application.owner(),application.model(),after,actor.userId());
            } else if(jdbc.update("""
                    UPDATE llm_quota SET total_tokens=?,version=version+1,updated_by=?,updated_at=UTC_TIMESTAMP(6)
                    WHERE id=? AND version=? AND total_tokens=?
                    """,after,actor.userId(),personal.id(),personal.version(),before)!=1)throw inconsistent();
            var granted=personal(application.owner(),application.model(),true);
            jdbc.update("""
                    INSERT INTO llm_usage(account_id,root_operation_id,operation_id,entry_key,entry_type,
                        reserved_delta,spent_delta,limit_before,limit_after,request_sha256,actor_user_id,created_at)
                    VALUES(?,?,?,'APPROVAL','LIMIT_CHANGE',0,0,?,?,?,?,UTC_TIMESTAMP(6))
                    """,granted.id(),application.cursor(),application.cursor(),before,after,hash,actor.userId());
        }
        var result=new PersonalModelQuotaWorkflow.DecisionV1(action,actor.userId(),requestId,hash,reason,expectedVersion,before,after);
        String body=write(result);long revision=Math.addExact(application.version(),1);
        if(jdbc.update("""
                UPDATE workflow_instance SET status=?,decider_user_id=?,revision=?,updated_at=UTC_TIMESTAMP(6),
                    finished_at=UTC_TIMESTAMP(6),result_version=1,result_json=?,result_sha256=?
                WHERE id=? AND kind='LLM_QUOTA_APPLICATION' AND status='PENDING' AND revision=? AND result_json IS NULL
                """,next,actor.userId(),revision,body,sha(body),application.cursor(),expectedVersion)!=1)throw conflict();
        audit(application,actor.userId(),requestId,action,next,hash,reason,revision);
        return view(locked(application.id()));
    }

    /** Every writer takes actual user rows in ascending ID order before any workflow/account lock. */
    private BusinessUserDirectory.Identity lockParticipants(BusinessUserDirectory.Identity actor,Long applicant) {
        var ids=new TreeSet<Long>();ids.add(actor.userId());if(applicant!=null)ids.add(applicant);
        for(long id:ids)if(jdbc.queryForList("SELECT id FROM users WHERE id=? FOR UPDATE",Long.class,id).size()!=1)throw forbidden();
        return users.lockCurrent(actor.userId(),actor.username());
    }
    private void requireConfigured(String model) {
        // Publishing/disabling a database-backed catalogue takes this control row exclusively.
        jdbc.queryForList("SELECT namespace FROM runtime_state WHERE namespace='MODEL_CONFIG_CONTROL' AND owner_id=0 AND scope_key='GLOBAL' FOR SHARE");
        if(models.entries().stream().noneMatch(entry->entry.id().equals(model)&&entry.configured()))
            throw new BusinessException(409,"模型当前未配置或已停用，不能申请或批准额度");
    }
    private BusinessUserDirectory.Identity current() {
        var actor=users.authenticated();return users.current(actor.userId(),actor.username());
    }
    private String enterpriseBlockedReason(String model) {
        var rows=jdbc.query("""
                SELECT total_tokens,reserved_tokens,spent_tokens,unreconciled_legacy_attempts,
                    expires_at,UTC_TIMESTAMP(6) AS checked_at FROM llm_quota
                WHERE scope_type='MODEL' AND subject_key=0 AND model_id=? AND period_key='TOTAL'
                """,com.ruanzhu.doorhandle.common.LocalDateTimeRow::read,model);
        if(!rows.isEmpty()) {
            var account=rows.get(0);Long total=account.get("total_tokens")==null?null:((Number)account.get("total_tokens")).longValue();
            if(total!=null&&((Number)account.get("unreconciled_legacy_attempts")).longValue()>0)return "HISTORY_UNRECONCILED";
            var expiry=(LocalDateTime)account.get("expires_at");
            if(expiry!=null&&!expiry.isAfter((LocalDateTime)account.get("checked_at")))return "EXPIRED";
            if(total!=null&&Math.subtractExact(Math.subtractExact(total,((Number)account.get("spent_tokens")).longValue()),
                    ((Number)account.get("reserved_tokens")).longValue())<=0)return "LIMIT_REACHED";
        }
        var observed=jdbc.queryForList("SELECT quantity FROM audit_event WHERE kind='MODEL_QUOTA_OBSERVATION' "
                +"AND observation_model_id=? ORDER BY observed_at DESC,id DESC LIMIT 1",Long.class,model);
        return !observed.isEmpty()&&observed.get(0)==0?"OBSERVED_EXHAUSTED":null;
    }
    private long owner(String id) {
        var rows=jdbc.queryForList("SELECT owner_user_id FROM workflow_instance WHERE kind='LLM_QUOTA_APPLICATION' AND workflow_id=?",Long.class,id);
        if(rows.size()!=1)throw new BusinessException(404,"额度申请不存在");return rows.get(0);
    }
    private Stored locked(String id) {
        var rows=jdbc.query("SELECT * FROM workflow_instance WHERE kind='LLM_QUOTA_APPLICATION' AND workflow_id=? FOR UPDATE",this::stored,id);
        if(rows.size()!=1)throw new BusinessException(404,"额度申请不存在");return rows.get(0);
    }
    private Personal personal(long owner,String model,boolean lock) {
        var rows=jdbc.query("SELECT id,total_tokens,reserved_tokens,spent_tokens,version,expires_at FROM llm_quota "
                +"WHERE scope_type='USER' AND owner_user_id=? AND model_id=? AND period_key='TOTAL'"+(lock?" FOR UPDATE":""),
                (rs,index)->new Personal(rs.getLong("id"),rs.getObject("total_tokens",Long.class),rs.getLong("reserved_tokens"),
                        rs.getLong("spent_tokens"),rs.getLong("version"),rs.getObject("expires_at",LocalDateTime.class)),owner,model);
        if(rows.size()>1)throw inconsistent();return rows.isEmpty()?null:rows.get(0);
    }
    private boolean receipt(long actor,String request,String application,String action,String hash) {
        var rows=jdbc.queryForList("SELECT resource_id,action,content_sha256 FROM audit_event WHERE kind='LLM_QUOTA_APPLICATION' "
                +"AND request_scope=? AND request_id=? FOR SHARE",JdbcWorkflowStore.ownerScope(actor),request);
        if(rows.isEmpty())return false;
        if(rows.size()!=1||!application.equals(rows.get(0).get("resource_id"))||!action.equals(rows.get(0).get("action"))
                ||!hash.equals(rows.get(0).get("content_sha256")))throw conflict();return true;
    }
    private void audit(Stored value,long actor,String request,String action,String state,String hash,String reason,long revision) {
        audits.appendQuotaApplication(new AuditEvent("LLM_QUOTA_APPLICATION",value.owner(),actor,"LLM_QUOTA_APPLICATION",
                value.id(),null,null,null,request,action,revision,hash,null,1,
                new PersonalModelQuotaWorkflow.AuditV1(value.model(),value.requestedTokens(),reason)),state);
    }
    private Stored stored(ResultSet rs,int ignored)throws SQLException {
        return new Stored(rs.getLong("id"),rs.getString("workflow_id"),rs.getLong("owner_user_id"),rs.getString("resource_id"),
                rs.getLong("requested_tokens"),rs.getString("request_sha256"),rs.getString("status"),rs.getLong("revision"),
                rs.getString("payload_json"),rs.getString("result_json"),rs.getObject("result_version",Integer.class),
                rs.getString("result_sha256"),rs.getObject("decider_user_id",Long.class),rs.getObject("created_at",LocalDateTime.class),
                rs.getObject("updated_at",LocalDateTime.class),rs.getObject("finished_at",LocalDateTime.class));
    }
    private Application view(Stored row) {
        var payload=read(row.payload(),PersonalModelQuotaWorkflow.ApplicationV1.class);protocol.validatePayload(payload,1);
        var result="PENDING".equals(row.status())?null:decision(row);
        return new Application(row.id(),row.cursor(),row.model(),row.owner(),row.requestedTokens(),payload.reason(),row.status(),row.version(),
                utc(row.created()),utc(row.updated()),utc(row.finished()),row.decider(),result==null?null:result.reason());
    }
    private PersonalModelQuotaWorkflow.DecisionV1 decision(Stored row) {
        if(row.result()==null||!Objects.equals(row.resultVersion(),1)||!sha(row.result()).equals(row.resultHash()))throw inconsistent();
        var result=read(row.result(),PersonalModelQuotaWorkflow.DecisionV1.class);
        String status=Map.of("APPROVE","APPROVED","REJECT","REJECTED","CANCEL","CANCELLED").get(result.decision());
        if(!row.status().equals(status)||!Objects.equals(row.decider(),result.actorUserId())||result.expectedVersion()+1!=row.version())throw inconsistent();
        return result;
    }
    private <T>T read(String body,Class<T> type) {
        try{return json.readValue(body,type);}catch(Exception error){throw inconsistent();}
    }
    private String write(Object value) {
        try{return json.writeValueAsString(value);}catch(Exception error){throw inconsistent();}
    }
    private static String sha(String value) {
        try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}
        catch(Exception error){throw inconsistent();}
    }
    private static OffsetDateTime utc(LocalDateTime value){return value==null?null:value.atOffset(ZoneOffset.UTC);}
    private static void validateModel(String id){try{ModelBudgetWorkflow.model(id);}catch(IllegalArgumentException invalid){throw bad("模型标识格式不正确");}}
    private static void identity(String id){if(id==null||!id.matches("[a-fA-F0-9]{8}(-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}"))throw bad("申请编号不正确");}
    private static void requestId(String id){if(id==null||!id.matches("[A-Za-z0-9_-]{8,128}"))throw bad("请求编号不正确");}
    private static void version(Long version){if(version==null||version<0||version==Long.MAX_VALUE)throw bad("申请版本不正确");}
    private static String reason(String value){if(value==null||value.isBlank()||value.length()>500)throw bad("申请或审批理由须为 1 到 500 字");return value.strip();}
    private static BusinessException bad(String message){return new BusinessException(400,message);}
    private static BusinessException forbidden(){return new BusinessException(403,"当前账号无权执行此额度操作");}
    private static BusinessException conflict(){return new BusinessException(409,"申请已更新或请求编号已用于不同操作，请刷新后确认");}
    private static IllegalStateException inconsistent(){return new IllegalStateException("个人额度回执与账本不一致");}
}
