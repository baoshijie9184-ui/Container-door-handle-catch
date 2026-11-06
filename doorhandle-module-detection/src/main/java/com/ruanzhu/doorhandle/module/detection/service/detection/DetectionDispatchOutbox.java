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
    private final DetectionExecutionPersistence persistence;
    private final TransactionTemplate tx;
    private final ObjectMapper json;
    private final DetectionTaskEventPublisher publisher;
    private final BusinessUserDirectory users;
    private final OperationsAuditApi audit;
    private final AtomicBoolean busy=new AtomicBoolean();
    private final ExecutorService delivery=Executors.newSingleThreadExecutor(r->{var thread=new Thread(r,"detection-outbox-delivery");thread.setDaemon(true);return thread;});

    public DetectionDispatchOutbox(JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper json,
                                   DetectionTaskEventPublisher publisher,BusinessUserDirectory users,OperationsAuditApi audit){
        this.persistence=new DetectionExecutionPersistence(jdbc,json);this.tx=new TransactionTemplate(manager);this.tx.setTimeout(5);this.json=json;this.publisher=publisher;this.users=users;this.audit=audit;
    }
    @PostConstruct void validate(){persistence.validateSchema();}
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
        var previous=persistence.dispatch(event.getTaskId(),event.getDispatchId());
        if(!previous.isEmpty()){
            if(!fingerprint.equals(previous.get(0).get("payload_sha256")))throw new IllegalStateException("同一检测派发编号的消息内容冲突");
            return (String)previous.get(0).get("event_id");
        }
        persistence.enqueue(event.getEventId(),event.getTaskId(),event.getDispatchId(),encoded(event),fingerprint,current.userId(),request);
        audit.append(new OperationsAuditApi.Event(new AgentActor(current.userId(),current.username(),current.supervisor()?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR),"ENTERPRISE","DETECTION","DISPATCH_ENQUEUED",event.getTaskId(),request,"APPLIED",null));
        return event.getEventId();
    }

    private DetectionExecutionPersistence.Delivery claim(){return tx.execute(status->persistence.claimDelivery());}
    boolean publishOne(){
        var claimed=claim();if(claimed==null)return false;
        DetectionTaskCreatedEvent event;
        try{event=json.readValue(claimed.payload(),DetectionTaskCreatedEvent.class);if(!claimed.fingerprint().equals(fingerprint(event))||!claimed.taskId().equals(event.getTaskId())||!claimed.dispatchId().equals(event.getDispatchId())||!claimed.eventId().equals(event.getEventId()))throw new IllegalStateException();}catch(Exception invalid){
            persistence.deliveryReview(claimed);return true;
        }
        try{
            publisher.publishCreated(event);
            persistence.deliverySent(claimed);
        }catch(RuntimeException unavailable){
            LocalDateTime now=persistence.now();
            long seconds=Math.min(60,1L<<Math.min(6,claimed.attempts()));
            persistence.deliveryRetry(claimed,now.plusSeconds(seconds));
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
