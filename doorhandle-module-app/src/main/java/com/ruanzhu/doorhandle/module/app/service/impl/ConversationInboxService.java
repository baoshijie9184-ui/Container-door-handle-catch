package com.ruanzhu.doorhandle.module.app.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.JdbcOwnerLock;
import com.ruanzhu.doorhandle.framework.persistence.workflow.*;
import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowPayloads.ConversationInputV1;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatSendMessageRequest;
import com.ruanzhu.doorhandle.module.app.service.*;
import com.ruanzhu.doorhandle.module.system.security.*;
import jakarta.annotation.*;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.*;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.*;
import java.util.concurrent.*;

/** Durable explicit input, with workflow identity and fenced one-shot dispatch. */
@Service
@ConditionalOnProperty(prefix="agentscope.conversation-control",name="enabled",havingValue="true")
public class ConversationInboxService implements AgentSteeringInboxApi {
    private static final WorkflowKind KIND=WorkflowKind.CONVERSATION_INPUT;
    private static final Set<String> PENDING=Set.of("QUEUED","STARTED");
    public record Item(String id,String mode,String status,int revision,String content,String targetRunId,
                       String clockStatus,Map<String,String> sourceWallTimes){
        public Item(String id,String mode,String status,int revision,String content,String targetRunId){this(id,mode,status,revision,content,targetRunId,"UTC",Map.of());}
        public Item { clockStatus=clockStatus==null?"UTC":clockStatus;sourceWallTimes=sourceWallTimes==null?Map.of():Collections.unmodifiableMap(new LinkedHashMap<>(sourceWallTimes)); }
    }
    private final JdbcTemplate jdbc; private final TransactionTemplate tx;
    private final JdbcWorkflowStore workflows; private final JdbcAuditStore audits;
    private final ChatSessionService sessions; private final ChatConversationService chat;
    private final BusinessUserDirectory users; private final ObjectProvider<AgentConversationControlApi> control;
    private ObjectProvider<AgentWorkbenchApi> workbench;
    @org.springframework.beans.factory.annotation.Autowired public void setWorkbench(ObjectProvider<AgentWorkbenchApi> workbench){this.workbench=workbench;}
    private final ThreadPoolExecutor workers=new ThreadPoolExecutor(2,2,0,TimeUnit.SECONDS,new SynchronousQueue<>(),r->{var t=new Thread(r,"agent-conversation-inbox");t.setDaemon(true);return t;});
    private final ScheduledExecutorService scheduler=Executors.newSingleThreadScheduledExecutor(r->{var t=new Thread(r,"agent-conversation-input-dispatch");t.setDaemon(true);return t;});
    private long dispatchAfterUser,dispatchRoundMaxUser;
    public ConversationInboxService(JdbcTemplate jdbc,PlatformTransactionManager manager,ChatSessionService sessions,ChatConversationService chat,
            BusinessUserDirectory users,ObjectProvider<AgentConversationControlApi> control){
        this.jdbc=jdbc;this.sessions=sessions;this.chat=chat;this.users=users;this.control=control;
        var json=new ObjectMapper();workflows=new JdbcWorkflowStore(jdbc,json);audits=new JdbcAuditStore(jdbc,json);
        tx=new TransactionTemplate(manager);tx.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);tx.setTimeout(5);
    }
    @PostConstruct public void schema(){
        try{JdbcOwnerLock.validateSchema(jdbc);workflows.validateSchema();audits.validateSchema();}
        catch(org.springframework.dao.DataAccessException error){throw new IllegalStateException("对话控制需要先执行 compact/005-workflow-runtime.sql",error);}
        if(control.getIfAvailable()==null)throw new IllegalStateException("对话控制需要 AgentScope 运行控制与日志");
    }
    @org.springframework.context.event.EventListener(org.springframework.boot.context.event.ApplicationReadyEvent.class)
    public void startDispatcher(){scheduler.scheduleWithFixedDelay(()->{try{dispatch();}catch(RuntimeException error){org.slf4j.LoggerFactory.getLogger(getClass()).warn("对话消息队列暂不可调度，请稍后刷新状态");}},1,1,TimeUnit.SECONDS);}
    private AgentActor fresh(AgentActor actor){var identity=users.current(actor.userId(),actor.username());return new AgentActor(identity.userId(),identity.username(),identity.supervisor()?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR);}
    private AgentActor owned(AgentActor actor,String session){var current=fresh(actor);var owner=sessions.resolveTenantForSystemCallback(session);if(owner.userId()!=current.userId())throw fail(404,"会话不存在或无权限");sessions.verifySessionOwner(current.username(),session);return current;}
    private void lock(long user){JdbcOwnerLock.lock(jdbc,JdbcOwnerLock.Scope.CONVERSATION_INPUT,user);}
    private LocalDateTime now(){return workflows.now();}
    private static String hash(String content){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(content.getBytes(StandardCharsets.UTF_8)));}catch(Exception error){throw new IllegalStateException(error);}}
    private ConversationInputV1 body(WorkflowRecord row){return workflows.payload(row,ConversationInputV1.class);}
    private void audit(WorkflowRecord row,String action){audits.append(new AuditEvent("CONVERSATION_INPUT",row.ownerUserId(),row.ownerUserId(),"CONVERSATION_INPUT",row.workflowId(),row.sessionId(),row.runId(),null,row.requestId(),action,row.revision(),body(row).contentSha256(),null,1,new AuditPayloads.ConversationInputV1(row.status())));}
    private WorkflowRecord row(long user,String id){var row=workflows.find(KIND,id).orElseThrow(()->fail(404,"消息不存在或无权限"));if(row.ownerUserId()!=user)throw fail(404,"消息不存在或无权限");return row;}
    private Item item(WorkflowRecord row){var body=body(row);var clock=row.legacyClockEvidence();return new Item(row.workflowId(),body.mode(),row.status(),Math.toIntExact(row.revision()),body.content(),row.runId(),clock==null?"UTC":clock.clockStatus(),clock==null?Map.of():clock.sourceWallTimes());}
    public List<Item> list(AgentActor actor,String session){var current=owned(actor,session);return workflows.list(KIND,current.userId(),session,null,Set.of(),false,50,false).stream().map(this::item).toList();}
    public Item enqueue(AgentActor actor,String session,String id,String mode,String content){return enqueue(actor,session,id,mode,content,"CHAT");}
    public Item enqueue(AgentActor actor,String session,String id,String mode,String content,String entryPoint){
        var current=owned(actor,session);
        if(!Set.of("CHAT","AGUI").contains(entryPoint))throw fail(400,"消息入口无效");
        if(id==null||!id.matches("[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}")||!Set.of("NEXT_TURN","NEXT_STEP").contains(mode)||content==null||content.isBlank()||content.length()>("NEXT_STEP".equals(mode)?4000:8000))throw fail(400,"消息编号、模式或长度无效");
        String digest=hash(current.userId()+"|"+session.length()+":"+session+"|"+mode+"|"+entryPoint+"|"+hash(content));
        return tx.execute(status->{
            lock(current.userId());var previous=workflows.find(KIND,id);
            if(previous.isPresent()){
                var old=previous.get();if(old.ownerUserId()!=current.userId()||!digest.equals(old.requestSha256()))throw fail(409,"消息编号已使用，请核对原提交");requireCurrentClock(old);return item(old);
            }
            if(workflows.count(KIND,current.userId(),null,null,PENDING)>=16)throw fail(429,"本人待处理消息已达 16 条，请等待或撤回");
            var run=control.getObject().inspect(current,session);String target=null,actualMode=mode;
            if("NEXT_STEP".equals(mode)&&run.runId()!=null){
                if(workflows.count(KIND,current.userId(),null,run.runId(),Set.of("QUEUED","APPLIED"))>=6)throw fail(429,"本轮补充要求已达上限，请使用排队发送");target=run.runId();
            }else actualMode="NEXT_TURN";
            var payload=new ConversationInputV1(current.username(),actualMode,mode,entryPoint,content,hash(content));
            var saved=workflows.create(new WorkflowDraft(id,KIND,"GLOBAL",id,digest,current.userId(),current.userId(),null,"SESSION",session,null,session,target,"QUEUED",now().plusMinutes(15),1,payload));
            audit(saved,"ENQUEUED");return item(saved);
        });
    }
    public Item change(AgentActor actor,String session,String id,int revision,String content){
        var current=owned(actor,session);if(content!=null&&(content.isBlank()||content.length()>8000))throw fail(400,"消息内容长度无效");
        return tx.execute(status->{lock(current.userId());var entry=row(current.userId(),id);var payload=body(entry);
            if(!session.equals(entry.sessionId()))throw fail(404,"消息不存在或无权限");
            requireCurrentClock(entry);
            if(!"QUEUED".equals(entry.status())||entry.revision()!=revision)throw fail(409,"消息状态已变化，请刷新核对");
            if(content!=null&&"NEXT_STEP".equals(payload.mode())&&content.length()>4000)throw fail(400,"补充要求最多 4000 字符");
            var updated=workflows.transition(entry,content==null?"CANCELLED":"QUEUED",payload.withContent(content==null?"":content,content==null?payload.contentSha256():hash(content)),entry.runId(),null,entry.expiresAt());
            audit(updated,content==null?"CANCELLED":"EDITED");return item(updated);
        });
    }
    public Item steer(AgentActor actor,String session,String id,int revision,String expectedRunId){
        var current=owned(actor,session);
        return tx.execute(status->{lock(current.userId());var entry=row(current.userId(),id);var payload=body(entry);
            if(!session.equals(entry.sessionId()))throw fail(404,"消息不存在或无权限");
            requireCurrentClock(entry);
            if(!"QUEUED".equals(entry.status())||!"NEXT_TURN".equals(payload.mode())||entry.revision()!=revision)throw fail(409,"消息状态已变化，请刷新核对");
            if(!entry.expiresAt().isAfter(now()))throw fail(409,"消息已过期，请刷新核对");
            if(payload.content().length()>4000)throw fail(400,"补充要求最多 4000 字符，请先编辑消息");
            var run=control.getObject().inspect(current,session);
            if(run.runId()==null||!run.runId().equals(expectedRunId)||"IDLE".equals(run.phase()))throw fail(409,"当前任务已变化，请刷新后重新选择引导");
            if(workflows.count(KIND,current.userId(),null,run.runId(),Set.of("QUEUED","APPLIED"))>=6)throw fail(429,"本轮补充要求已达上限，请保留排队或稍后重试");
            var updated=workflows.transition(entry,"QUEUED",payload.withMode("NEXT_STEP"),run.runId(),null,entry.expiresAt());
            audit(updated,"PROMOTED_NEXT_STEP");return item(updated);
        });
    }
    @Override public List<Input> take(AgentActor actor,String session,String runId){
        var current=owned(actor,session);
        return tx.execute(status->{lock(current.userId());var result=new ArrayList<Input>();
            for(var entry:workflows.list(KIND,current.userId(),session,runId,Set.of("QUEUED"),true,6,true)){
                if(entry.legacyClockUnresolved())continue;
                var payload=body(entry);if(!"NEXT_STEP".equals(payload.mode()))continue;
                result.add(new Input(entry.workflowId(),payload.content()));
                sessions.appendUserMessage(new TenantContext(current.userId(),current.username()),session,payload.content());
                audit(workflows.transition(entry,"APPLIED",payload.withContent("",payload.contentSha256()),entry.runId(),null,entry.expiresAt()),"APPLIED_AT_BOUNDARY");
            }return result;
        });
    }
    public synchronized void dispatch(){
        if(workers.isShutdown())return;
        expire();if(workers.getActiveCount()>=2)return;
        if(dispatchRoundMaxUser==0||dispatchAfterUser>=dispatchRoundMaxUser)startDispatchRound();
        var owners=queuedOwnersAfter(dispatchAfterUser);
        if(owners.isEmpty()&&dispatchAfterUser!=0){startDispatchRound();owners=queuedOwnersAfter(0);}
        for(long owner:owners){dispatchAfterUser=owner;for(var candidate:workflows.list(KIND,owner,null,null,Set.of("QUEUED"),false,16,true))if(dispatch(candidate))return;}
    }
    private void startDispatchRound(){dispatchAfterUser=0;dispatchRoundMaxUser=workflows.maxOwner(KIND,"QUEUED");}
    private List<Long> queuedOwnersAfter(long after){return workflows.ownersAfter(KIND,"QUEUED",after,dispatchRoundMaxUser,32);}
    private record Claimed(WorkflowRecord claim,ConversationInputV1 original){}
    private boolean dispatch(WorkflowRecord candidate){
        if(candidate.legacyClockUnresolved())return false;
        long user=candidate.ownerUserId();String session=candidate.sessionId(),id=candidate.workflowId();AgentActor actor;
        try{actor=owned(new AgentActor(user,body(candidate).username(),AgentActor.Role.INSPECTOR),session);}catch(RuntimeException error){failQueued(user,id,"ACCOUNT_OR_SESSION_UNAVAILABLE");return false;}
        var run=control.getObject().inspect(actor,session);
        if(workbench!=null&&workbench.getIfAvailable()!=null&&!workbench.getObject().canDispatchInput(actor,session,id))return false;
        if(!"IDLE".equals(run.phase()))return false;
        Claimed claimed=tx.execute(status->{lock(user);var entry=row(user,id);if(!"QUEUED".equals(entry.status()))return null;
            if(entry.legacyClockUnresolved())return null;
            if(workflows.count(KIND,user,session,null,Set.of("STARTED"))>0||!entry.expiresAt().isAfter(now()))return null;
            var payload=body(entry);
            if("NEXT_STEP".equals(payload.mode())){entry=workflows.transition(entry,"QUEUED",payload.withMode("NEXT_TURN"),null,null,entry.expiresAt());audit(entry,"FALLBACK_NEXT_TURN");payload=body(entry);}
            Duration lease=Duration.ofSeconds(control.getObject().maxRunSeconds()+10L);
            var started=workflows.claim(entry,"STARTED",payload.withContent("",payload.contentSha256()),entry.runId(),now().plus(lease),lease);
            audit(started,"STARTED");return new Claimed(started,payload);
        });
        if(claimed==null)return false;
        try{workers.execute(()->execute(actor,session,claimed));}catch(RejectedExecutionException error){finish(claimed,"FAILED","EXECUTOR_UNAVAILABLE");}
        return true;
    }
    private void execute(AgentActor supplied,String session,Claimed claimed){
        var previous=SecurityContextHolder.getContext();
        try{
            var actor=owned(supplied,session);var roles=List.of(new SimpleGrantedAuthority("ROLE_"+actor.role().name()));
            var security=SecurityContextHolder.createEmptyContext();security.setAuthentication(new UsernamePasswordAuthenticationToken(new TenantPrincipal(actor.userId(),actor.username(),"",roles),null,roles));SecurityContextHolder.setContext(security);
            var request=new ChatSendMessageRequest();request.setSessionId(session);request.setContent(claimed.original().content());
            chat.handleQueuedMessage(actor.username(),request,claimed.claim().workflowId(),claimed.original().entryPoint());finish(claimed,"COMPLETED","COMPLETED");
        }catch(RuntimeException error){finish(claimed,"FAILED","EXECUTION_FAILED_NO_AUTO_RETRY");}
        finally{SecurityContextHolder.setContext(previous);}
    }
    private void finish(Claimed claimed,String state,String action){tx.executeWithoutResult(status->{lock(claimed.claim().ownerUserId());var current=row(claimed.claim().ownerUserId(),claimed.claim().workflowId());
        if(current.legacyClockUnresolved())return;
        if(!"STARTED".equals(current.status())||!Objects.equals(current.claimToken(),claimed.claim().claimToken())||current.fence()!=claimed.claim().fence())return;
        if(!current.expiresAt().isAfter(now()))return;
        audit(workflows.finishClaim(claimed.claim(),state,body(current),null),action);
    });}
    private void failQueued(long user,String id,String action){tx.executeWithoutResult(status->{lock(user);var entry=row(user,id);if(!"QUEUED".equals(entry.status()))return;var payload=body(entry);
        if(entry.legacyClockUnresolved())return;
        audit(workflows.transition(entry,"FAILED",payload.withContent("",payload.contentSha256()),entry.runId(),null,entry.expiresAt()),action);
    });}
    public void expire(){for(var candidate:workflows.expired(KIND,PENDING,50))tx.executeWithoutResult(status->{lock(candidate.ownerUserId());var entry=row(candidate.ownerUserId(),candidate.workflowId());
        if(entry.legacyClockUnresolved())return;
        if(!PENDING.contains(entry.status())||entry.expiresAt().isAfter(now()))return;var payload=body(entry);
        audit(workflows.expireConversationInput(entry,payload.withContent("",payload.contentSha256())),"EXPIRED");
    });}
    private static void requireCurrentClock(WorkflowRecord row){if(row.legacyClockUnresolved())throw fail(409,"历史时区未确认，原消息期限和状态需要核对，不能自动执行或重放");}
    private static ResponseStatusException fail(int code,String message){return new ResponseStatusException(HttpStatus.valueOf(code),message);}
    @PreDestroy public void close(){scheduler.shutdownNow();workers.shutdown();awaitShutdown(scheduler,2);awaitShutdown(workers,5);}
    private void awaitShutdown(ExecutorService executor,long seconds){try{if(!executor.awaitTermination(seconds,TimeUnit.SECONDS))executor.shutdownNow();}catch(InterruptedException error){executor.shutdownNow();Thread.currentThread().interrupt();}}
}
