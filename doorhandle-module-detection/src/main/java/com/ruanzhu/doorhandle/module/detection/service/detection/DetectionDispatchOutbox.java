package com.ruanzhu.doorhandle.module.detection.service.detection;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.detection.DetectionTaskCreatedEvent;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import jakarta.annotation.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.*;
import org.springframework.transaction.annotation.*;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.context.request.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** The business transaction records intent; bounded background delivery only resends the same event. */
@Service
@ConditionalOnProperty(prefix="detection.commands",name="enabled",havingValue="true")
public class DetectionDispatchOutbox implements AutoCloseable {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final ObjectMapper json;
    private final DetectionTaskEventPublisher publisher;
    private final BusinessUserDirectory users;
    private final OperationsAuditApi audit;
    private final AtomicBoolean busy=new AtomicBoolean();
    private final ExecutorService delivery=Executors.newSingleThreadExecutor(r->{var thread=new Thread(r,"detection-outbox-delivery");thread.setDaemon(true);return thread;});

    public DetectionDispatchOutbox(JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper json,
                                   DetectionTaskEventPublisher publisher,BusinessUserDirectory users,OperationsAuditApi audit){
        this.jdbc=jdbc;this.tx=new TransactionTemplate(manager);this.tx.setTimeout(5);this.json=json;this.publisher=publisher;this.users=users;this.audit=audit;
    }
    @PostConstruct void validate(){jdbc.queryForList("SELECT id FROM detection_dispatch_outbox WHERE 1=0");}
    private String encoded(Object value){try{return json.writeValueAsString(value);}catch(Exception error){throw new IllegalStateException("检测消息编码失败");}}
    private String digest(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(Exception error){throw new IllegalStateException("检测消息摘要失败");}}
    private String fingerprint(DetectionTaskCreatedEvent event){var tree=json.valueToTree(event);((com.fasterxml.jackson.databind.node.ObjectNode)tree).remove(List.of("eventId","eventTime"));return digest(encoded(tree));}
    private void token(String value,int max){if(value==null||!value.matches("[A-Za-z0-9_-]{1,"+max+"}"))throw new IllegalArgumentException("检测命令编号无效");}

    @Transactional(propagation=Propagation.MANDATORY)
    public String enqueue(DetectionTaskCreatedEvent event){
        var authentication=SecurityContextHolder.getContext().getAuthentication();
        if(authentication==null||!authentication.isAuthenticated()||!(authentication.getPrincipal() instanceof TenantPrincipal principal))throw new SecurityException("检测派发缺少受信账号");
        var identity=users.current(principal.userId(),principal.username());
        var actor=new AgentActor(identity.userId(),identity.username(),identity.supervisor()?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR);
        String request=UUID.randomUUID().toString();var attributes=RequestContextHolder.getRequestAttributes();
        if(attributes instanceof ServletRequestAttributes servlet){var header=servlet.getRequest().getHeader("X-Request-ID");if(header!=null){token(header,128);request=header;}}
        return enqueue(event,actor,request);
    }

    @Transactional(propagation=Propagation.MANDATORY)
    public String enqueue(DetectionTaskCreatedEvent event,AgentActor actor,String request){
        if(!org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive())throw new IllegalStateException("检测消息必须与业务变更在同一事务保存");
        var current=users.current(actor.userId(),actor.username());
        token(event.getTaskId(),128);token(event.getDispatchId(),64);token(event.getEventId(),128);token(request,128);
        String fingerprint=fingerprint(event);
        // The task's dispatch update already holds its row lock for competing confirmation requests.
        var previous=jdbc.queryForList("SELECT event_id,payload_sha256 FROM detection_dispatch_outbox WHERE task_id=? AND dispatch_id=?",event.getTaskId(),event.getDispatchId());
        if(!previous.isEmpty()){
            if(!fingerprint.equals(previous.get(0).get("payload_sha256")))throw new IllegalStateException("同一检测派发编号的消息内容冲突");
            return (String)previous.get(0).get("event_id");
        }
        jdbc.update("INSERT INTO detection_dispatch_outbox(event_id,task_id,dispatch_id,payload_json,payload_sha256,actor_user_id,request_id,status,next_attempt_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'PENDING',CURRENT_TIMESTAMP(6),CURRENT_TIMESTAMP(6),CURRENT_TIMESTAMP(6))",
                event.getEventId(),event.getTaskId(),event.getDispatchId(),encoded(event),fingerprint,current.userId(),request);
        audit.append(new OperationsAuditApi.Event(new AgentActor(current.userId(),current.username(),current.supervisor()?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR),"ENTERPRISE","DETECTION","DISPATCH_ENQUEUED",event.getTaskId(),request,"APPLIED",null));
        return event.getEventId();
    }

    private record Claimed(long id,String token,String payload,String fingerprint,String taskId,String dispatchId,String eventId,int attempts){}
    private Claimed claim(){return tx.execute(status->{
        var rows=jdbc.queryForList("SELECT id,event_id,task_id,dispatch_id,payload_json,payload_sha256,attempts FROM detection_dispatch_outbox WHERE (status='PENDING' AND next_attempt_at<=CURRENT_TIMESTAMP(6)) OR (status='SENDING' AND lease_until<CURRENT_TIMESTAMP(6)) ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED");
        if(rows.isEmpty())return null;
        var row=rows.get(0);long id=((Number)row.get("id")).longValue();String token=UUID.randomUUID().toString();
        LocalDateTime now=jdbc.queryForObject("SELECT CURRENT_TIMESTAMP(6)",LocalDateTime.class);
        jdbc.update("UPDATE detection_dispatch_outbox SET status='SENDING',attempts=attempts+1,lease_token=?,lease_until=?,updated_at=CURRENT_TIMESTAMP(6) WHERE id=?",token,now.plusMinutes(2),id);
        return new Claimed(id,token,(String)row.get("payload_json"),(String)row.get("payload_sha256"),(String)row.get("task_id"),(String)row.get("dispatch_id"),(String)row.get("event_id"),((Number)row.get("attempts")).intValue()+1);
    });}
    boolean publishOne(){
        var claimed=claim();if(claimed==null)return false;
        DetectionTaskCreatedEvent event;
        try{event=json.readValue(claimed.payload(),DetectionTaskCreatedEvent.class);if(!claimed.fingerprint().equals(fingerprint(event))||!claimed.taskId().equals(event.getTaskId())||!claimed.dispatchId().equals(event.getDispatchId())||!claimed.eventId().equals(event.getEventId()))throw new IllegalStateException();}catch(Exception invalid){
            jdbc.update("UPDATE detection_dispatch_outbox SET status='NEEDS_REVIEW',last_error_code='INVALID_STORED_EVENT',lease_token=NULL,lease_until=NULL,updated_at=CURRENT_TIMESTAMP(6) WHERE id=? AND status='SENDING' AND lease_token=?",claimed.id(),claimed.token());return true;
        }
        try{
            publisher.publishCreated(event);
            jdbc.update("UPDATE detection_dispatch_outbox SET status='SENT',last_error_code=NULL,lease_token=NULL,lease_until=NULL,updated_at=CURRENT_TIMESTAMP(6) WHERE id=? AND status='SENDING' AND lease_token=?",claimed.id(),claimed.token());
        }catch(RuntimeException unavailable){
            LocalDateTime now=jdbc.queryForObject("SELECT CURRENT_TIMESTAMP(6)",LocalDateTime.class);
            long seconds=Math.min(60,1L<<Math.min(6,claimed.attempts()));
            jdbc.update("UPDATE detection_dispatch_outbox SET status='PENDING',last_error_code='ACK_UNCONFIRMED',next_attempt_at=?,lease_token=NULL,lease_until=NULL,updated_at=CURRENT_TIMESTAMP(6) WHERE id=? AND status='SENDING' AND lease_token=?",now.plusSeconds(seconds),claimed.id(),claimed.token());
            // An uncertain broker acknowledgement is safe to resend only with durable worker deduplication enabled.
        }
        return true;
    }
    @Scheduled(fixedDelay=1000) public void schedule(){
        if(!busy.compareAndSet(false,true))return;
        try{delivery.submit(()->{try{for(int count=0;count<8&&!Thread.currentThread().isInterrupted()&&publishOne();count++);}finally{busy.set(false);}});}catch(RejectedExecutionException stopped){busy.set(false);}
    }
    @Override @PreDestroy public void close(){delivery.shutdownNow();}
}
