package com.ruanzhu.doorhandle.module.detection.service.report;

import com.ruanzhu.doorhandle.module.detection.config.properties.ReportEventProperties;
import com.ruanzhu.doorhandle.module.detection.repository.ReportEventRepository;
import com.ruanzhu.doorhandle.contracts.detection.ReportLifecycleEvent;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;
import java.time.*;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;

/** 短语句竞争租约，网络发送在事务外；确认丢失时允许重投，由接收端去重。 */
@Service
@ConditionalOnProperty(prefix="app.report-events",name="enabled",havingValue="true")
public class ReportEventDispatcher {
    private static final org.slf4j.Logger log=org.slf4j.LoggerFactory.getLogger(ReportEventDispatcher.class);
    private final ReportEventRepository repository;private final ReportEventTransport transport;private final ReportEventProperties properties;
    private final ReportEventCodec codec;private final Clock clock;private final AtomicBoolean running=new AtomicBoolean();
    private java.util.concurrent.ScheduledExecutorService executor;
    public ReportEventDispatcher(ReportEventRepository repository,ReportEventTransport transport,ReportEventProperties properties,ReportEventCodec codec,@Qualifier("reportEventClock") Clock clock){
        this.repository=repository;this.transport=transport;this.properties=properties;this.codec=codec;this.clock=clock;
    }
    @jakarta.annotation.PostConstruct
    public void start(){
        executor=java.util.concurrent.Executors.newSingleThreadScheduledExecutor(task->{var thread=new Thread(task,"report-event-delivery");thread.setDaemon(true);return thread;});
        executor.scheduleWithFixedDelay(this::poll,properties.getInitialDelayMs(),properties.getPollDelayMs(),java.util.concurrent.TimeUnit.MILLISECONDS);
    }
    @jakarta.annotation.PreDestroy public void stop(){if(executor!=null)executor.shutdownNow();}
    public void poll(){try{drain();}catch(RuntimeException error){log.warn("Report event polling deferred: errorType={}",error.getClass().getSimpleName());}}
    public int drain(){
        if(!running.compareAndSet(false,true))return 0;
        int sent=0;
        try{
            for(var entry:repository.due(now(),properties.getBatchSize())){
                ReportLifecycleEvent event=null;
                try{event=validated(entry);}catch(IllegalArgumentException ignored){}
                if(event!=null&&hasEarlierUndelivered(event)){repository.defer(entry,now().plusSeconds(5));continue;}
                String token=UUID.randomUUID().toString();
                if(!repository.claim(entry,token,now(),now().plusNanos(properties.getLeaseMs()*1_000_000)))continue;
                if(event==null){repository.failed(entry.eventId(),token,"INVALID_EVENT",true,now());continue;}
                try{transport.send(event.reportId(),entry.payload());}
                catch(InterruptedException error){Thread.currentThread().interrupt();repository.failed(entry.eventId(),token,"SEND_INTERRUPTED",false,next(entry.attempts()+1));break;}
                catch(Exception error){repository.failed(entry.eventId(),token,"BROKER_UNAVAILABLE",false,next(entry.attempts()+1));continue;}
                // 数据库确认失败则保留租约，重启或过期后重投，不能把 broker 确认丢失当成未发送。
                if(repository.delivered(entry.eventId(),token,now()))sent++;
            }
            return sent;
        }finally{running.set(false);}
    }
    private ReportLifecycleEvent validated(ReportEventRepository.Entry row){
        var event=codec.decode(row.payload());
        if(!row.eventId().equals(event.eventId())||!row.reportId().equals(event.reportId())||!row.eventType().equals(event.eventType()))throw new IllegalArgumentException("Invalid report event binding");
        return event;
    }
    private boolean hasEarlierUndelivered(ReportLifecycleEvent event){
        for(var sibling:repository.siblings(event.reportId())){
            if(sibling.eventId().equals(event.eventId())||"DELIVERED".equals(sibling.status()))continue;
            try{if(validated(sibling).version()<=event.version())return true;}
            catch(IllegalArgumentException error){return true;}
        }
        return false;
    }
    private LocalDateTime now(){return LocalDateTime.now(clock);}
    private LocalDateTime next(int attempt){long delay=properties.getRetryBaseMs();for(int i=1;i<Math.min(attempt,32)&&delay<properties.getRetryMaxMs();i++)delay=Math.min(properties.getRetryMaxMs(),delay*2);return now().plusNanos(delay*1_000_000);}
}
