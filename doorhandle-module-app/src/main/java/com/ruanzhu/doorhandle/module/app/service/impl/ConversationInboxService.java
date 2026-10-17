package com.ruanzhu.doorhandle.module.app.service.impl;

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
import java.time.LocalDateTime;
import java.util.*;
import java.util.concurrent.*;

/** 只有用户明确提交的普通消息进入后台队列，steering 在 SDK 安全切点交付。 */
@Service
@ConditionalOnProperty(prefix="agentscope.conversation-control",name="enabled",havingValue="true")
public class ConversationInboxService implements AgentSteeringInboxApi {
    public record Item(String id,String mode,String status,int revision,String content,String targetRunId){}
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;
    private final ChatSessionService sessions;private final ChatConversationService chat;
    private final BusinessUserDirectory users;private final ObjectProvider<AgentConversationControlApi> control;
    private ObjectProvider<AgentWorkbenchApi> workbench;
    @org.springframework.beans.factory.annotation.Autowired public void setWorkbench(ObjectProvider<AgentWorkbenchApi> workbench){this.workbench=workbench;}
    private final ThreadPoolExecutor workers=new ThreadPoolExecutor(2,2,0,TimeUnit.SECONDS,new SynchronousQueue<>(),r->{var t=new Thread(r,"agent-conversation-inbox");t.setDaemon(true);return t;});
    private final ScheduledExecutorService scheduler=Executors.newSingleThreadScheduledExecutor(r->{var t=new Thread(r,"agent-conversation-input-dispatch");t.setDaemon(true);return t;});
    public ConversationInboxService(JdbcTemplate jdbc,PlatformTransactionManager manager,ChatSessionService sessions,ChatConversationService chat,
            BusinessUserDirectory users,ObjectProvider<AgentConversationControlApi> control){
        this.jdbc=jdbc;this.sessions=sessions;this.chat=chat;this.users=users;this.control=control;
        tx=new TransactionTemplate(manager);tx.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);tx.setTimeout(5);
    }
    @PostConstruct public void schema(){
        try{jdbc.queryForList("SELECT user_id FROM agent_conversation_input_owner WHERE 1=0");jdbc.queryForList("SELECT input_id,active_slot FROM agent_conversation_input WHERE 1=0");jdbc.queryForList("SELECT input_id FROM agent_conversation_input_audit WHERE 1=0");}
        catch(org.springframework.dao.DataAccessException error){throw new IllegalStateException("对话控制需要先执行 migration-V36-conversation-inbox.sql");}
        if(control.getIfAvailable()==null)throw new IllegalStateException("对话控制需要 AgentScope 运行控制与日志");
    }
    @org.springframework.context.event.EventListener(org.springframework.boot.context.event.ApplicationReadyEvent.class)
    public void startDispatcher(){scheduler.scheduleWithFixedDelay(()->{try{dispatch();}catch(RuntimeException error){org.slf4j.LoggerFactory.getLogger(getClass()).warn("对话消息队列暂不可调度，请稍后刷新状态");}},1,1,TimeUnit.SECONDS);}
    private AgentActor fresh(AgentActor actor){var identity=users.current(actor.userId(),actor.username());return new AgentActor(identity.userId(),identity.username(),identity.supervisor()?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR);}
    private AgentActor owned(AgentActor actor,String session){var current=fresh(actor);var owner=sessions.resolveTenantForSystemCallback(session);if(owner.userId()!=current.userId())throw fail(404,"会话不存在或无权限");sessions.verifySessionOwner(current.username(),session);return current;}
    private void lock(long user){jdbc.update("INSERT INTO agent_conversation_input_owner(user_id) VALUES(?) ON DUPLICATE KEY UPDATE user_id=VALUES(user_id)",user);jdbc.queryForObject("SELECT user_id FROM agent_conversation_input_owner WHERE user_id=? FOR UPDATE",Long.class,user);}
    private LocalDateTime now(){return jdbc.queryForObject("SELECT CURRENT_TIMESTAMP(6)",LocalDateTime.class);}
    private static String hash(String content){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(content.getBytes(StandardCharsets.UTF_8)));}catch(Exception error){throw new IllegalStateException(error);}}
    private void audit(Map<String,Object> row,String action){jdbc.update("INSERT INTO agent_conversation_input_audit(input_id,user_id,action,revision,content_sha256) VALUES(?,?,?,?,?)",row.get("input_id"),row.get("user_id"),action,row.get("revision"),row.get("content_sha256"));}
    private Map<String,Object> row(long user,String id){var rows=jdbc.queryForList("SELECT * FROM agent_conversation_input WHERE user_id=? AND input_id=?",user,id);if(rows.isEmpty())throw fail(404,"消息不存在或无权限");return rows.get(0);}
    private Item item(Map<String,Object> row){return new Item((String)row.get("input_id"),(String)row.get("mode"),(String)row.get("status"),((Number)row.get("revision")).intValue(),(String)row.get("content"),(String)row.get("target_run_id"));}
    public List<Item> list(AgentActor actor,String session){var current=owned(actor,session);return jdbc.queryForList("SELECT * FROM agent_conversation_input WHERE user_id=? AND session_id=? ORDER BY id DESC LIMIT 50",current.userId(),session).stream().map(this::item).toList();}
    public Item enqueue(AgentActor actor,String session,String id,String mode,String content){
        return enqueue(actor,session,id,mode,content,"CHAT");
    }
    public Item enqueue(AgentActor actor,String session,String id,String mode,String content,String entryPoint){
        var current=owned(actor,session);
        if(!Set.of("CHAT","AGUI").contains(entryPoint))throw fail(400,"消息入口无效");
        if(id==null||!id.matches("[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}")||!Set.of("NEXT_TURN","NEXT_STEP").contains(mode)||content==null||content.isBlank()||content.length()>("NEXT_STEP".equals(mode)?4000:8000))throw fail(400,"消息编号、模式或长度无效");
        return tx.execute(status->{
            lock(current.userId());var previous=jdbc.queryForList("SELECT * FROM agent_conversation_input WHERE input_id=?",id);
            if(!previous.isEmpty()){
                var old=previous.get(0);if(!Objects.equals(old.get("user_id"),current.userId())||!session.equals(old.get("session_id"))||!entryPoint.equals(old.get("entry_point"))||!mode.equals(old.get("requested_mode"))||!hash(content).equals(old.get("content_sha256")))throw fail(409,"消息编号已使用，请核对原提交");return item(old);
            }
            Long pending=jdbc.queryForObject("SELECT COUNT(*) FROM agent_conversation_input WHERE user_id=? AND status IN ('QUEUED','STARTED')",Long.class,current.userId());
            if(pending>=16)throw fail(429,"本人待处理消息已达 16 条，请等待或撤回");
            var run=control.getObject().inspect(current,session);String target=null,actualMode=mode;
            if("NEXT_STEP".equals(mode)&&run.runId()!=null){
                Long count=jdbc.queryForObject("SELECT COUNT(*) FROM agent_conversation_input WHERE user_id=? AND target_run_id=? AND status IN ('QUEUED','APPLIED')",Long.class,current.userId(),run.runId());
                if(count>=6)throw fail(429,"本轮补充要求已达上限，请使用排队发送");target=run.runId();
            }else actualMode="NEXT_TURN";
            jdbc.update("INSERT INTO agent_conversation_input(input_id,user_id,username,session_id,mode,requested_mode,entry_point,target_run_id,content,content_sha256,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",id,current.userId(),current.username(),session,actualMode,mode,entryPoint,target,content,hash(content),now().plusMinutes(15));
            var saved=row(current.userId(),id);audit(saved,"ENQUEUED");return item(saved);
        });
    }
    public Item change(AgentActor actor,String session,String id,int revision,String content){
        var current=owned(actor,session);if(content!=null&&(content.isBlank()||content.length()>8000))throw fail(400,"消息内容长度无效");
        return tx.execute(status->{lock(current.userId());var entry=row(current.userId(),id);
            if(!session.equals(entry.get("session_id")))throw fail(404,"消息不存在或无权限");
            if(!"QUEUED".equals(entry.get("status"))||((Number)entry.get("revision")).intValue()!=revision)throw fail(409,"消息状态已变化，请刷新核对");
            if(content!=null&&"NEXT_STEP".equals(entry.get("mode"))&&content.length()>4000)throw fail(400,"补充要求最多 4000 字符");
            jdbc.update("UPDATE agent_conversation_input SET content=?,content_sha256=?,status=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE input_id=?",content==null?"":content,content==null?entry.get("content_sha256"):hash(content),content==null?"CANCELLED":"QUEUED",id);
            var updated=row(current.userId(),id);audit(updated,content==null?"CANCELLED":"EDITED");return item(updated);
        });
    }
    /** Promote an existing pending message; preserve its identity, source, original request mode and deadline. */
    public Item steer(AgentActor actor,String session,String id,int revision,String expectedRunId){
        var current=owned(actor,session);
        return tx.execute(status->{lock(current.userId());var entry=row(current.userId(),id);
            if(!session.equals(entry.get("session_id")))throw fail(404,"消息不存在或无权限");
            if(!"QUEUED".equals(entry.get("status"))||!"NEXT_TURN".equals(entry.get("mode"))||((Number)entry.get("revision")).intValue()!=revision)throw fail(409,"消息状态已变化，请刷新核对");
            if(jdbc.queryForObject("SELECT COUNT(*) FROM agent_conversation_input WHERE input_id=? AND expires_at>CURRENT_TIMESTAMP",Integer.class,id)!=1)throw fail(409,"消息已过期，请刷新核对");
            if(((String)entry.get("content")).length()>4000)throw fail(400,"补充要求最多 4000 字符，请先编辑消息");
            var run=control.getObject().inspect(current,session);
            if(run.runId()==null||!run.runId().equals(expectedRunId)||"IDLE".equals(run.phase()))throw fail(409,"当前任务已变化，请刷新后重新选择引导");
            Long count=jdbc.queryForObject("SELECT COUNT(*) FROM agent_conversation_input WHERE user_id=? AND target_run_id=? AND status IN ('QUEUED','APPLIED')",Long.class,current.userId(),run.runId());
            if(count>=6)throw fail(429,"本轮补充要求已达上限，请保留排队或稍后重试");
            jdbc.update("UPDATE agent_conversation_input SET mode='NEXT_STEP',target_run_id=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE input_id=?",run.runId(),id);
            var updated=row(current.userId(),id);audit(updated,"PROMOTED_NEXT_STEP");return item(updated);
        });
    }
    @Override public List<Input> take(AgentActor actor,String session,String runId){
        var current=owned(actor,session);
        return tx.execute(status->{lock(current.userId());var result=new ArrayList<Input>();
            for(var entry:jdbc.queryForList("SELECT * FROM agent_conversation_input WHERE user_id=? AND session_id=? AND target_run_id=? AND mode='NEXT_STEP' AND status='QUEUED' AND expires_at>CURRENT_TIMESTAMP ORDER BY id LIMIT 6",current.userId(),session,runId)){
                String content=(String)entry.get("content");result.add(new Input((String)entry.get("input_id"),content));
                sessions.appendUserMessage(new TenantContext(current.userId(),current.username()),session,content);
                jdbc.update("UPDATE agent_conversation_input SET status='APPLIED',content='',revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE input_id=?",entry.get("input_id"));
                audit(row(current.userId(),(String)entry.get("input_id")),"APPLIED_AT_BOUNDARY");
            }return result;
        });
    }
    /** 仅领取未执行过的消息，重启不会重放 STARTED。 */
    public synchronized void dispatch(){
        if(workers.isShutdown())return;
        expire();if(workers.getActiveCount()>=2)return;
        for(var candidate:jdbc.queryForList("SELECT * FROM agent_conversation_input WHERE status='QUEUED' ORDER BY id LIMIT 32")){
            long user=((Number)candidate.get("user_id")).longValue();String username=(String)candidate.get("username"),session=(String)candidate.get("session_id"),id=(String)candidate.get("input_id");
            AgentActor actor;
            try{actor=owned(new AgentActor(user,username,AgentActor.Role.INSPECTOR),session);}catch(RuntimeException error){terminal(user,id,"FAILED","ACCOUNT_OR_SESSION_UNAVAILABLE");continue;}
            var run=control.getObject().inspect(actor,session);
            if(workbench!=null&&workbench.getIfAvailable()!=null&&!workbench.getObject().canDispatchInput(actor,session,id))continue;
            if(!"IDLE".equals(run.phase()))continue;
            Map<String,Object> claimed=tx.execute(status->{lock(user);var entry=row(user,id);if(!"QUEUED".equals(entry.get("status")))return null;
                if(jdbc.queryForObject("SELECT COUNT(*) FROM agent_conversation_input WHERE user_id=? AND session_id=? AND status='STARTED'",Integer.class,user,session)>0)return null;
                if(jdbc.queryForObject("SELECT COUNT(*) FROM agent_conversation_input WHERE input_id=? AND expires_at>CURRENT_TIMESTAMP",Integer.class,id)==0)return null;
                if("NEXT_STEP".equals(entry.get("mode"))){jdbc.update("UPDATE agent_conversation_input SET mode='NEXT_TURN',target_run_id=NULL WHERE input_id=?",id);audit(entry,"FALLBACK_NEXT_TURN");}
                jdbc.update("UPDATE agent_conversation_input SET status='STARTED',active_slot=1,content='',revision=revision+1,expires_at=?,updated_at=CURRENT_TIMESTAMP WHERE input_id=?",now().plusSeconds(control.getObject().maxRunSeconds()+10),id);audit(row(user,id),"STARTED");return entry;
            });
            if(claimed==null)continue;
            try{workers.execute(()->execute(actor,session,id,(String)claimed.get("content"),(String)claimed.get("entry_point")));}
            catch(RejectedExecutionException error){terminal(user,id,"FAILED","EXECUTOR_UNAVAILABLE");}
            return;
        }
    }
    private void execute(AgentActor supplied,String session,String id,String content,String entryPoint){
        var previous=SecurityContextHolder.getContext();
        try{
            var actor=owned(supplied,session);var roles=List.of(new SimpleGrantedAuthority("ROLE_"+actor.role().name()));
            var security=SecurityContextHolder.createEmptyContext();security.setAuthentication(new UsernamePasswordAuthenticationToken(new TenantPrincipal(actor.userId(),actor.username(),"",roles),null,roles));SecurityContextHolder.setContext(security);
            var request=new ChatSendMessageRequest();request.setSessionId(session);request.setContent(content);
            chat.handleQueuedMessage(actor.username(),request,id,entryPoint);terminal(actor.userId(),id,"COMPLETED","COMPLETED");
        }catch(RuntimeException error){terminal(supplied.userId(),id,"FAILED","EXECUTION_FAILED_NO_AUTO_RETRY");}
        finally{SecurityContextHolder.setContext(previous);}
    }
    private void terminal(long user,String id,String state,String action){tx.executeWithoutResult(status->{lock(user);var entry=row(user,id);if(!Set.of("QUEUED","STARTED").contains(entry.get("status")))return;
        jdbc.update("UPDATE agent_conversation_input SET status=?,active_slot=NULL,content='',revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE input_id=?",state,id);audit(row(user,id),action);
    });}
    public void expire(){for(var entry:jdbc.queryForList("SELECT user_id,input_id FROM agent_conversation_input WHERE status IN ('QUEUED','STARTED') AND expires_at<=CURRENT_TIMESTAMP ORDER BY id LIMIT 50")){
        long user=((Number)entry.get("user_id")).longValue();String id=(String)entry.get("input_id");
        tx.executeWithoutResult(status->{lock(user);var row=row(user,id);if(!Set.of("QUEUED","STARTED").contains(row.get("status"))||jdbc.queryForObject("SELECT COUNT(*) FROM agent_conversation_input WHERE input_id=? AND expires_at<=CURRENT_TIMESTAMP",Integer.class,id)==0)return;
            jdbc.update("UPDATE agent_conversation_input SET status='EXPIRED',active_slot=NULL,content='',revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE input_id=?",id);audit(row(user,id),"EXPIRED");});
    }}
    private static ResponseStatusException fail(int code,String message){return new ResponseStatusException(HttpStatus.valueOf(code),message);}
    @PreDestroy public void close(){scheduler.shutdownNow();workers.shutdownNow();}
}
