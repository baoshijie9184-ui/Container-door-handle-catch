package com.ruanzhu.doorhandle.module.ai.action;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.config.*;
import com.ruanzhu.doorhandle.module.ai.journal.AgentJournal;
import jakarta.annotation.PostConstruct;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.*;

/** 操作提议与业务执行分开；确认只加载已存参数，业务更新和必要审计共用单体事务。 */
@Service
@EnableConfigurationProperties(AgentActionProperties.class)
public class AgentActionService {
    public static final String TOOL="propose_quality_assignment";
    public static final String POLICY="quality-assignment-confirmation-v2";
    public static final String RETRY_TOOL="propose_detection_retry";
    public static final String RETRY_POLICY="detection-retry-confirmation-v1";
    public static final String CREATE_TOOL="propose_detection_creation";
    public static final String CREATE_POLICY="detection-creation-confirmation-v2";
    public record View(String actionId,String runId,String sessionId,String operation,String status,long version,
                       DetectionAssignmentApi.Command command,DetectionAssignmentApi.Values before,
                       DetectionAssignmentApi.Applied result,String reasonCode,LocalDateTime createdAt,LocalDateTime expiresAt,
                       DetectionExecutionApi.RetryPreview retry,DetectionExecutionApi.Receipt execution,
                       DetectionCreationApi.Preview creation,DetectionCreationApi.Receipt creationResult) {
        public View(String actionId,String runId,String sessionId,String operation,String status,long version,
                    DetectionAssignmentApi.Command command,DetectionAssignmentApi.Values before,DetectionAssignmentApi.Applied result,
                    String reasonCode,LocalDateTime createdAt,LocalDateTime expiresAt) {
            this(actionId,runId,sessionId,operation,status,version,command,before,result,reasonCode,createdAt,expiresAt,null,null,null,null);
        }
        public View(String actionId,String runId,String sessionId,String operation,String status,long version,
                    DetectionAssignmentApi.Command command,DetectionAssignmentApi.Values before,DetectionAssignmentApi.Applied result,
                    String reasonCode,LocalDateTime createdAt,LocalDateTime expiresAt,DetectionExecutionApi.RetryPreview retry,DetectionExecutionApi.Receipt execution) {
            this(actionId,runId,sessionId,operation,status,version,command,before,result,reasonCode,createdAt,expiresAt,retry,execution,null,null);
        }
    }
    public record Audit(long id,String eventType,String actorRole,String result,String reasonCode,LocalDateTime occurredAt) {}
    private record Stored(View view,String resourceVersion,String digest,String policy,long userId) {}
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final ObjectMapper json;
    private final AgentActionPersistence persistence;
    private final AgentJournal journal;
    private final DetectionAssignmentApi assignments;
    private final AgentActionProperties properties;
    private DetectionExecutionApi detection;
    @org.springframework.beans.factory.annotation.Autowired(required=false)
    public void setDetectionExecution(DetectionExecutionApi detection) { this.detection=detection; }
    public boolean retryEnabled() { return enabled() && detection!=null; }
    private DetectionCreationApi creation;
    @org.springframework.beans.factory.annotation.Autowired(required=false)
    public void setDetectionCreation(DetectionCreationApi creation){this.creation=creation;}
    public boolean creationEnabled(){return enabled()&&creation!=null;}
    public AgentActionService(JdbcTemplate jdbc,PlatformTransactionManager transactions,ObjectMapper json,
            AgentJournal journal,DetectionAssignmentApi assignments,AgentActionProperties properties) {
        this.jdbc=jdbc;this.tx=new TransactionTemplate(transactions);this.json=json;this.journal=journal;
        this.persistence=new AgentActionPersistence(jdbc,json);
        this.tx.setIsolationLevel(org.springframework.transaction.TransactionDefinition.ISOLATION_READ_COMMITTED);
        this.assignments=assignments;this.properties=properties;
    }
    public boolean enabled() { return properties.isEnabled(); }
    @PostConstruct public void verifySchema() {
        if (!enabled()) return;
        if (!journal.enabled()) throw new IllegalStateException("启用人工确认前必须启用持久运行日志");
        try { persistence.validateSchema(); }
        catch (RuntimeException error) { throw new IllegalStateException("请完成 compact 人工确认迁移再启用该功能",error); }
    }
    public View propose(AgentActor actor,String runId,String callId,DetectionAssignmentApi.Command command) {
        requireEnabled();actor.requireSupervisor();validateId(runId);
        if (callId!=null && !callId.matches("[A-Za-z0-9_:.-]{1,160}")) throw bad("调用编号格式不正确");
        return tx.execute(ignored->{
            // 锁住运行，避免取消已提交后仍接受新的提议，也串行化同一运行的幂等键。
            var run=jdbc.queryForList("SELECT session_id,status FROM agent_run WHERE user_id=? AND run_id=? FOR UPDATE",actor.userId(),runId);
            if (run.isEmpty()) throw missing();
            if (!Set.of("RUNNING","COMPLETED").contains(run.get(0).get("status").toString())) throw conflict("该运行不再接受操作提议");
            var preview=assignments.preview(actor,command);
            String normalized=write(preview.command()), digest=digest(normalized);
            var duplicates=persistence.byArguments(actor.userId(),runId,digest).stream().map(this::stored).toList();
            if (!duplicates.isEmpty()) return expire(actor,duplicates.get(0)).view();
            var prior=persistence.pendingResource(actor.userId(),preview.command().taskId()).stream().map(this::stored).toList();
            for (var old:prior) close(actor,old,"INVALIDATED","PARAMETERS_SUPERSEDED","CONFIRMATION_INVALIDATED");
            Integer count=persistence.count(actor.userId(),runId);
            if (count!=null && count>=20) throw conflict("单次运行的操作提议已达上限");
            String id=UUID.randomUUID().toString(),session=run.get(0).get("session_id").toString();
            LocalDateTime now=now();
            persistence.create(id,actor.userId(),runId,session,callId,"ASSIGN_QUALITY_TASK",preview.command().taskId(),preview.resourceVersion(),digest,normalized,write(preview.before()),POLICY,now.plusMinutes(10));
            var saved=load(actor,id,false);
            audit(actor,saved,"CONFIRMATION_CREATED","PENDING",null);
            return saved.view();
        });
    }
    /** Only records an immutable proposal. The model cannot approve this operation. */
    public View proposeRetry(AgentActor actor,String runId,String callId,String taskId) {
        requireEnabled();if(!retryEnabled())throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"检测执行功能尚未启用");
        validateId(runId);validateId(taskId);
        if(callId!=null&&!callId.matches("[A-Za-z0-9_:.-]{1,160}"))throw bad("调用编号格式不正确");
        return tx.execute(ignored->{
            var run=jdbc.queryForList("SELECT session_id,status FROM agent_run WHERE user_id=? AND run_id=? FOR UPDATE",actor.userId(),runId);
            if(run.isEmpty())throw missing();
            if(!Set.of("RUNNING","COMPLETED").contains(run.get(0).get("status").toString()))throw conflict("该运行不再接受操作提议");
            var preview=detection.previewRetry(actor,taskId);
            var command=new DetectionExecutionApi.RetryApproval(preview.taskId(),preview.resourceVersion());
            String arguments=digest(write(List.of("RETRY_DETECTION",command,preview)));
            var duplicates=persistence.byArguments(actor.userId(),runId,arguments).stream().map(this::stored).toList();
            if(!duplicates.isEmpty())return expire(actor,duplicates.get(0)).view();
            var prior=persistence.pendingResource(actor.userId(),taskId).stream().map(this::stored).toList();
            for(var old:prior)close(actor,old,"INVALIDATED","PARAMETERS_SUPERSEDED","CONFIRMATION_INVALIDATED");
            Integer count=persistence.count(actor.userId(),runId);
            if(count!=null&&count>=20)throw conflict("单次运行的操作提议已达上限");
            String id=UUID.randomUUID().toString();
            persistence.create(id,actor.userId(),runId,(String)run.get(0).get("session_id"),callId,"RETRY_DETECTION",taskId,preview.resourceVersion(),arguments,write(command),write(preview),RETRY_POLICY,now().plusMinutes(10));
            var saved=load(actor,id,false);audit(actor,saved,"CONFIRMATION_CREATED","PENDING",null);return saved.view();
        });
    }
    public View proposeCreation(AgentActor actor,String runId,String callId,DetectionCreationApi.Request request){
        return proposeCreation(actor,runId,callId,request,null);
    }
    public View proposeCreation(AgentActor actor,String runId,String callId,DetectionCreationApi.Request request,String replacesActionId){
        requireEnabled();if(!creationEnabled())throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"会话图片创建检测尚未启用");
        validateId(runId);if(callId!=null&&!callId.matches("[A-Za-z0-9_:.-]{1,160}"))throw bad("调用编号格式不正确");
        if(replacesActionId!=null)validateId(replacesActionId);
        var initial=jdbc.queryForList("SELECT session_id,status FROM agent_run WHERE user_id=? AND run_id=?",actor.userId(),runId);
        if(initial.isEmpty())throw missing();if(!Set.of("RUNNING","COMPLETED").contains(initial.get(0).get("status")))throw conflict("该运行不再接受操作提议");
        // Business originals may require bounded OSS reads; finish those before locking any proposal/run row.
        var prepared=creation.preview(actor,(String)initial.get(0).get("session_id"),request);
        return tx.execute(ignored->{
            var run=jdbc.queryForList("SELECT session_id,status FROM agent_run WHERE user_id=? AND run_id=? FOR UPDATE",actor.userId(),runId);
            if(run.isEmpty())throw missing();if(!Set.of("RUNNING","COMPLETED").contains(run.get(0).get("status")))throw conflict("该运行不再接受操作提议");
            String session=(String)run.get(0).get("session_id");if(!session.equals(prepared.sessionId()))throw conflict("会话已变化 请重新生成提议");creation.revalidate(actor,prepared);var preview=prepared;String body=write(preview),arguments=digest(body);
            if(replacesActionId!=null){var old=load(actor,replacesActionId,true);if(!runId.equals(old.view().runId())||old.view().creation()==null||!"PENDING".equals(old.view().status()))throw conflict("只能修改当前运行尚未确认的检测创建提议");}
            var duplicate=persistence.byArguments(actor.userId(),runId,arguments).stream().map(this::stored).toList();
            if(!duplicate.isEmpty())return expire(actor,duplicate.get(0)).view();
            Integer count=persistence.count(actor.userId(),runId);if(count>=20)throw conflict("单次运行的操作提议已达上限");
            String id=UUID.randomUUID().toString();
            // Disjoint batches can coexist; overlapping images or an explicit replacement supersede the old pending proposal.
            var ids=new HashSet<>(preview.images().stream().map(WorkspaceDetectionImagesApi.Image::fileId).toList());
            for(var old:persistence.pendingCreations(actor.userId(),runId).stream().map(this::stored).toList())
                if(Objects.equals(replacesActionId,old.view().actionId())||old.view().creation().images().stream().anyMatch(image->ids.contains(image.fileId())))
                    close(actor,old,"INVALIDATED","PARAMETERS_SUPERSEDED","CONFIRMATION_INVALIDATED");
            persistence.create(id,actor.userId(),runId,session,callId,"CREATE_DETECTION",id,preview.resourceVersion(),arguments,body,body,CREATE_POLICY,now().plusMinutes(10));
            var saved=load(actor,id,false);audit(actor,saved,"CONFIRMATION_CREATED","PENDING",null);return saved.view();
        });
    }
    public List<View> list(AgentActor actor,String sessionId,String runId,int limit) {
        requireEnabled();if (limit<1||limit>100) throw bad("分页数量必须在 1 到 100 之间");
        if (sessionId!=null&&!sessionId.matches("[A-Za-z0-9_.-]{1,128}"))throw bad("会话编号不正确");
        if (runId!=null)validateId(runId);
        var ids=persistence.ids(actor.userId(),sessionId,runId,limit);
        var visible=new ArrayList<View>();
        for(var id:ids)try{visible.add(get(actor,id));}catch(SecurityException|DetectionExecutionApi.ResourceChanged denied){/* Do not return a revoked or changed source snapshot. Minimal command reconciliation is a separate owner-scoped view. */}
        return List.copyOf(visible);
    }
    public View get(AgentActor actor,String id) {
        requireEnabled();validateId(id);
        return tx.execute(ignored->{var action=expire(actor,load(actor,id,true));
            if(action.view().retry()!=null){
                if(detection==null)throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"检测执行功能尚未启用");
                detection.assertReadable(actor,action.view().retry().taskId());
            }
            if(action.view().creation()!=null){
                if(creation==null)throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"会话图片创建检测尚未启用");
                creation.assertReadable(actor,action.view().creation());action=reconcileCreation(actor,action);
            }
            return action.view();
        });
    }
    public List<Audit> audit(AgentActor actor,String id) {
        get(actor,id);
        return persistence.audits(actor.userId(),id).stream().map(row->new Audit(row.id(),row.eventType(),row.actorRole(),row.result(),row.reasonCode(),display(row.occurredAt()))).toList();
    }
    public View decide(AgentActor actor,String id,long expectedVersion,String decision) {
        requireEnabled();validateId(id);
        if (expectedVersion<1 || !Set.of("APPROVE","REJECT","CANCEL").contains(Objects.toString(decision,""))) throw bad("确认决策或版本不正确");
        return tx.execute(ignored->{
            // 与提议一致采用 run -> action -> resource 的锁顺序，取消先提交时拒绝执行。
            var initial=load(actor,id,false);
            var origin="APPROVE".equals(decision)?jdbc.queryForList("SELECT status FROM agent_run WHERE user_id=? AND run_id=? FOR UPDATE",actor.userId(),initial.view().runId()):List.<Map<String,Object>>of();
            var action=expire(actor,load(actor,id,true));
            if (!"PENDING".equals(action.view().status())) {if(action.view().creation()!=null)return reconcileCreation(actor,action).view();return action.view();}
            if (action.view().version()!=expectedVersion) throw conflict("操作版本已变化，请刷新卡片");
            if (!"APPROVE".equals(decision)) return close(actor,action,"REJECT".equals(decision)?"REJECTED":"CANCELLED","USER_"+decision,"CONFIRMATION_DECIDED").view();
            if("RETRY_DETECTION".equals(action.view().operation()))return approveRetry(actor,action,origin);
            if("CREATE_DETECTION".equals(action.view().operation()))return approveCreation(actor,action,origin);
            if (!actor.supervisor()) return close(actor,action,"INVALIDATED","ROLE_REVOKED","AUTHORIZATION_DENIED").view();
            if (!POLICY.equals(action.policy())) return close(actor,action,"INVALIDATED","POLICY_CHANGED","CONFIRMATION_INVALIDATED").view();
            if (!digest(write(action.view().command())).equals(action.digest())) throw new IllegalStateException("已存参数校验失败，未执行分配");
            if (origin.isEmpty()||!Set.of("RUNNING","COMPLETED").contains(origin.get(0).get("status").toString())) return close(actor,action,"INVALIDATED","ORIGIN_RUN_TERMINATED","CONFIRMATION_INVALIDATED").view();
            // 以下只有单数据库写入；任何未知异常都回滚，保留 PENDING，不能将异常伪装为成功。
            DetectionAssignmentApi.Applied result;
            try {
                var current=assignments.preview(actor,action.view().command());
                if (!current.resourceVersion().equals(action.resourceVersion())) throw new DetectionAssignmentApi.ResourceChanged();
                audit(actor,action,"AUTHORIZATION_ALLOWED","APPROVED",null);
                audit(actor,action,"CONFIRMATION_DECIDED","APPROVED",null);
                audit(actor,action,"TOOL_EXECUTION_STARTED","EXECUTING",null);
                result=assignments.apply(actor,action.view().command(),action.resourceVersion());
            }
            catch (DetectionAssignmentApi.ResourceChanged error) { return close(actor,action,"INVALIDATED","RESOURCE_CHANGED","CONFIRMATION_INVALIDATED").view(); }
            catch (SecurityException error) { return close(actor,action,"INVALIDATED","ROLE_REVOKED","AUTHORIZATION_DENIED").view(); }
            catch (IllegalArgumentException error) { return close(actor,action,"INVALIDATED","BUSINESS_PRECONDITION_CHANGED","CONFIRMATION_INVALIDATED").view(); }
            persistence.result(actor.userId(),id,action.view().version(),write(result));
            audit(actor,action,"BUSINESS_CHANGED","SUCCEEDED",null);
            return close(actor,action,"SUCCEEDED",null,"TOOL_EXECUTION_COMPLETED").view();
        });
    }
    private View approveCreation(AgentActor actor,Stored action,List<Map<String,Object>> origin){
        if(!creationEnabled())throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"会话图片创建检测尚未启用");
        if(!CREATE_POLICY.equals(action.policy()))return close(actor,action,"INVALIDATED","POLICY_CHANGED","CONFIRMATION_INVALIDATED").view();
        if(!digest(write(action.view().creation())).equals(action.digest()))throw new IllegalStateException("检测创建参数摘要不匹配");
        if(origin.isEmpty()||!Set.of("RUNNING","COMPLETED").contains(origin.get(0).get("status")))return close(actor,action,"INVALIDATED","ORIGIN_RUN_TERMINATED","CONFIRMATION_INVALIDATED").view();
        var p=action.view().creation();
        try{
            creation.revalidate(actor,p);
        }catch(SecurityException denied){return close(actor,action,"INVALIDATED","ROLE_REVOKED","AUTHORIZATION_DENIED").view();}
        catch(DetectionExecutionApi.ResourceChanged changed){return close(actor,action,"INVALIDATED","RESOURCE_CHANGED","CONFIRMATION_INVALIDATED").view();}
        catch(IllegalArgumentException changed){return close(actor,action,"INVALIDATED","BUSINESS_PRECONDITION_CHANGED","CONFIRMATION_INVALIDATED").view();}
        audit(actor,action,"AUTHORIZATION_ALLOWED","APPROVED",null);audit(actor,action,"CONFIRMATION_DECIDED","APPROVED",null);
        var receipt=creation.reserve(actor,action.view().actionId(),action.view().actionId(),p);
        if(receipt==null||!"PREPARING".equals(receipt.status()))throw new IllegalStateException("检测创建命令未核实");
        persistence.result(actor.userId(),action.view().actionId(),action.view().version(),write(receipt));
        return close(actor,action,"EXECUTING",null,"TOOL_EXECUTION_STARTED").view();
    }
    private Stored reconcileCreation(AgentActor actor,Stored action){
        if(!Set.of("EXECUTING","NEEDS_REVIEW").contains(action.view().status())||creation==null)return action;
        var receipt=creation.receipt(actor,action.view().actionId());if(receipt.isEmpty())return action;
        String state=switch(receipt.get().status()){case "QUEUED"->"SUCCEEDED";case "NEEDS_REVIEW"->"NEEDS_REVIEW";case "CANCELLED"->"CANCELLED";default->"EXECUTING";};
        if(!state.equals(action.view().status())){
            persistence.reconcile(actor.userId(),action.view().actionId(),action.view().version(),action.view().status(),state,"NEEDS_REVIEW".equals(state)?"EXECUTION_NEEDS_REVIEW":"CANCELLED".equals(state)?"USER_ABANDONED":null,write(receipt.get()));
            audit(actor,action,"NEEDS_REVIEW".equals(state)?"TOOL_EXECUTION_UNCONFIRMED":"CANCELLED".equals(state)?"TOOL_EXECUTION_CANCELLED":"TOOL_EXECUTION_COMPLETED",state,"NEEDS_REVIEW".equals(state)?"EXECUTION_NEEDS_REVIEW":"CANCELLED".equals(state)?"USER_ABANDONED":null);
            return load(actor,action.view().actionId(),false);
        }
        return action;
    }
    private View approveRetry(AgentActor actor,Stored action,List<Map<String,Object>> origin) {
        if(!retryEnabled())throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"检测执行功能尚未启用");
        if(!RETRY_POLICY.equals(action.policy()))return close(actor,action,"INVALIDATED","POLICY_CHANGED","CONFIRMATION_INVALIDATED").view();
        var preview=action.view().retry();
        var command=new DetectionExecutionApi.RetryApproval(preview.taskId(),preview.resourceVersion());
        if(!Objects.equals(action.resourceVersion(),preview.resourceVersion()) || !digest(write(List.of("RETRY_DETECTION",command,preview))).equals(action.digest()))
            throw new IllegalStateException("已存检测参数校验失败，未执行重试");
        if(origin.isEmpty()||!Set.of("RUNNING","COMPLETED").contains(origin.get(0).get("status").toString()))return close(actor,action,"INVALIDATED","ORIGIN_RUN_TERMINATED","CONFIRMATION_INVALIDATED").view();
        try {
            var current=detection.previewRetry(actor,preview.taskId());
            if(!current.equals(preview))return close(actor,action,"INVALIDATED","RESOURCE_CHANGED","CONFIRMATION_INVALIDATED").view();
        } catch(DetectionExecutionApi.NeedsReview error) {
            return close(actor,action,"INVALIDATED","EXECUTION_NEEDS_REVIEW","CONFIRMATION_INVALIDATED").view();
        } catch(SecurityException error) {
            return close(actor,action,"INVALIDATED","ROLE_REVOKED","AUTHORIZATION_DENIED").view();
        } catch(IllegalArgumentException|com.ruanzhu.doorhandle.common.BusinessException error) {
            return close(actor,action,"INVALIDATED","BUSINESS_PRECONDITION_CHANGED","CONFIRMATION_INVALIDATED").view();
        }
        audit(actor,action,"AUTHORIZATION_ALLOWED","APPROVED",null);audit(actor,action,"CONFIRMATION_DECIDED","APPROVED",null);
        audit(actor,action,"TOOL_EXECUTION_STARTED","EXECUTING",null);
        // Joins this transaction. A failure after writes must roll back, never be converted to a closed success.
        var result=detection.retry(actor,action.view().actionId(),action.view().actionId(),command);
        if(result==null||!preview.taskId().equals(result.taskId())||!"RETRY".equals(result.operation())||!"QUEUED".equals(result.status()))
            throw new IllegalStateException("检测命令回执与批准参数不一致");
        persistence.result(actor.userId(),action.view().actionId(),action.view().version(),write(result));
        audit(actor,action,"BUSINESS_CHANGED","SUCCEEDED",null);
        return close(actor,action,"SUCCEEDED",null,"TOOL_EXECUTION_COMPLETED").view();
    }
    private Stored expire(AgentActor actor,Stored action) {
        if ("PENDING".equals(action.view().status()) && !action.view().expiresAt().minusHours(8).isAfter(now()))
            return close(actor,action,"EXPIRED","CONFIRMATION_EXPIRED","CONFIRMATION_INVALIDATED");
        return action;
    }
    private Stored close(AgentActor actor,Stored action,String state,String reason,String event) {
        persistence.close(actor.userId(),action.view().actionId(),action.view().version(),state,reason);
        audit(actor,action,event,state,reason);
        return load(actor,action.view().actionId(),false);
    }
    private void audit(AgentActor actor,Stored action,String event,String result,String reason) {
        persistence.appendAudit(actor.userId(),action.view().actionId(),action.view().runId(),event,actor.role().name(),action.view().creation()!=null?action.view().actionId():action.view().retry()==null?action.view().command().taskId():action.view().retry().taskId(),action.digest(),action.policy(),result,reason);
    }
    private Stored load(AgentActor actor,String id,boolean lock) {
        var row=persistence.find(actor.userId(),id,lock);
        if(row==null)throw missing();return stored(row);
    }
    private Stored stored(AgentActionPersistence.Row row) {
        var payload=row.proposal();String operation=payload.operation(),result=row.resultJson();
        boolean retry="RETRY_DETECTION".equals(operation);
        boolean create="CREATE_DETECTION".equals(operation);
        if(!retry&&!create&&!"ASSIGN_QUALITY_TASK".equals(operation))throw new IllegalStateException("不支持的确认操作类型");
        var creationPreview=create?read(payload.commandJson(),DetectionCreationApi.Preview.class):null;
        if(create&&(!creationPreview.equals(read(payload.beforeJson(),DetectionCreationApi.Preview.class))||!creationPreview.resourceVersion().equals(payload.resourceVersion())))throw new IllegalStateException("创建提议内容已变化");
        var preview=retry?read(payload.beforeJson(),DetectionExecutionApi.RetryPreview.class):null;
        if(retry&&!new DetectionExecutionApi.RetryApproval(preview.taskId(),preview.resourceVersion()).equals(read(payload.commandJson(),DetectionExecutionApi.RetryApproval.class)))
            throw new IllegalStateException("检测提议参数不一致");
        return new Stored(new View(row.actionId(),row.runId(),row.sessionId(),operation,row.status(),row.version(),
                retry||create?null:read(payload.commandJson(),DetectionAssignmentApi.Command.class),retry||create?null:read(payload.beforeJson(),DetectionAssignmentApi.Values.class),
                retry||create||result==null?null:read(result,DetectionAssignmentApi.Applied.class),row.reasonCode(),display(row.createdAt()),display(row.expiresAt()),
                preview,retry&&result!=null?read(result,DetectionExecutionApi.Receipt.class):null,creationPreview,create&&result!=null?read(result,DetectionCreationApi.Receipt.class):null),payload.resourceVersion(),row.digest(),payload.policyVersion(),row.userId());
    }
    private LocalDateTime now(){return persistence.now();}
    private static LocalDateTime display(LocalDateTime utc){return utc==null?null:utc.plusHours(8);}
    private String write(Object value) {try{return json.writeValueAsString(value);}catch(Exception error){throw new IllegalStateException("操作参数序列化失败");}}
    private <T> T read(String value,Class<T> type) {try{return json.readValue(value,type);}catch(Exception error){throw new IllegalStateException("操作记录格式不正确");}}
    private static String digest(String value) {try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(Exception error){throw new IllegalStateException(error);}}
    private void requireEnabled() {if(!enabled())throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"人工确认功能尚未启用");}
    private static void validateId(String value) {if(value==null||!value.matches("[A-Za-z0-9_-]{1,128}"))throw bad("操作或运行编号不正确");}
    private static ResponseStatusException bad(String message) {return new ResponseStatusException(HttpStatus.BAD_REQUEST,message);}
    private static ResponseStatusException conflict(String message) {return new ResponseStatusException(HttpStatus.CONFLICT,message);}
    private static ResponseStatusException missing() {return new ResponseStatusException(HttpStatus.NOT_FOUND,"操作或运行不存在");}
}
