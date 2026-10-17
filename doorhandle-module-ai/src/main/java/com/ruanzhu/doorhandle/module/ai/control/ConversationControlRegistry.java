package com.ruanzhu.doorhandle.module.ai.control;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.journal.AgentJournal;
import io.agentscope.core.agent.*;
import io.agentscope.core.event.AgentEvent;
import io.agentscope.core.message.*;
import io.agentscope.core.middleware.*;
import jakarta.annotation.PostConstruct;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Function;

@Service
@ConditionalOnProperty(prefix="agentscope.conversation-control",name="enabled",havingValue="true")
public class ConversationControlRegistry implements AgentConversationControlApi {
    private final AgentJournal journal;
    private final ObjectProvider<AgentSteeringInboxApi> inbox;
    private final com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory users;
    private final ConcurrentHashMap<String,Handle> live=new ConcurrentHashMap<>();
    private org.springframework.beans.factory.ObjectProvider<AgentWorkbenchApi> workbench;
    @org.springframework.beans.factory.annotation.Autowired
    public void setWorkbench(org.springframework.beans.factory.ObjectProvider<AgentWorkbenchApi> workbench){this.workbench=workbench;}
    public ConversationControlRegistry(AgentJournal journal,ObjectProvider<AgentSteeringInboxApi> inbox){this(journal,inbox,null);}
    @org.springframework.beans.factory.annotation.Autowired
    public ConversationControlRegistry(AgentJournal journal,ObjectProvider<AgentSteeringInboxApi> inbox,com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory users){this.journal=journal;this.inbox=inbox;this.users=users;}
    @PostConstruct void validate(){if(!journal.enabled())throw new IllegalStateException("对话控制需要启用 Agent 运行日志");}
    private String key(AgentActor actor,String session){return actor.userId()+":"+session;}
    public Handle attach(AgentActor actor,String session,AgentJournal.Run audit){
        var handle=new Handle(actor,session,audit);if(live.putIfAbsent(key(actor,session),handle)!=null)throw conflict("当前会话已有执行");return handle;
    }
    @Override public View inspect(AgentActor actor,String session){
        var handle=live.get(key(actor,session));if(handle!=null){var view=handle.view();if(!"ENDED".equals(view.phase()))return view;}
        if(workbench!=null&&workbench.getIfAvailable()!=null){String phase=workbench.getObject().waitingPhase(actor,session);if(phase!=null)return new View(session,null,phase,0,false,"");}
        var running=journal.list(actor,session,null,20).stream().filter(run->"RUNNING".equals(run.status())).findFirst();
        return running.map(run->new View(session,run.runId(),"REMOTE_RUNNING",0,false,""))
                .orElseGet(()->new View(session,null,"IDLE",0,false,""));
    }
    @Override public View command(AgentActor actor,String session,String runId,String action,long revision){
        journal.get(actor,runId);
        var handle=live.get(key(actor,session));
        if(handle==null||!handle.audit.id().equals(runId))throw conflict("执行已结束或不在此实例，请刷新核对");
        synchronized(handle){
            if(handle.revision!=revision)throw conflict("执行状态已变化，请刷新后重试");
            switch(action){
                case "pause"->{if(!handle.pausing){handle.audit.event("PAUSE_REQUESTED",Map.of("agent",handle.main()));handle.pausing=true;handle.phase="PAUSE_REQUESTED";handle.gate=Sinks.one();handle.revision++;}}
                case "resume"->{if(handle.pausing){handle.audit.event("RUN_RESUMED",Map.of("agent",handle.main()));handle.pausing=false;handle.phase="RUNNING";handle.revision++;handle.gate.tryEmitEmpty();}}
                case "cancel"->journal.cancel(actor,runId);
                default->throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"未知执行控制操作");
            }
            return handle.view();
        }
    }
    private static ResponseStatusException conflict(String text){return new ResponseStatusException(HttpStatus.CONFLICT,text);}
    public final class Handle implements MiddlewareBase,AutoCloseable {
        private final AgentActor actor;private final String session;private final AgentJournal.Run audit;
        private boolean pausing,closed;private long revision;
        private String phase="RUNNING";private StringBuilder text=new StringBuilder();private Sinks.One<Void> gate=Sinks.one();
        private final List<Msg> steering=new ArrayList<>();
        Handle(AgentActor actor,String session,AgentJournal.Run audit){this.actor=actor;this.session=session;this.audit=audit;}
        String main(){return actor.supervisor()?"supervisor-main":"employee-main";}
        public synchronized View view(){return new View(session,audit.id(),phase,revision,true,text.toString());}
        public synchronized void text(String chunk){if(!closed&&text.length()<64000)text.append(chunk,0,Math.min(chunk.length(),64000-text.length()));}
        private Mono<Void> boundary(){return Mono.defer(()->{
            synchronized(this){
                if(closed)return Mono.error(new CancellationException());
                if(!pausing)return Mono.empty();
                if(!"PAUSED".equals(phase)){audit.event("RUN_PAUSED",Map.of("agent",main()));phase="PAUSED";revision++;}
                return gate.asMono();
            }
        });}
        @Override public int order(){return -200;}
        private void authorizeBoundary(){
            if(users==null)return;
            try{var current=users.current(actor.userId(),actor.username());if(current.userId()!=actor.userId()||!current.username().equals(actor.username())||current.supervisor()!=actor.supervisor())throw new SecurityException();}
            catch(RuntimeException error){audit.event("AUTHORIZATION_DENIED",Map.of("agent",main(),"decision","DENY","scope","CURRENT_ACCOUNT","policyVersion","conversation-control-v1"));throw new org.springframework.security.access.AccessDeniedException("当前账号授权无法核实，请重新发起对话");}
        }
        @Override public Flux<AgentEvent> onModelCall(Agent agent,RuntimeContext context,ModelCallInput input,Function<ModelCallInput,Flux<AgentEvent>> next){
            return boundary().publishOn(reactor.core.scheduler.Schedulers.boundedElastic()).thenMany(Flux.defer(()->{
                authorizeBoundary();
                if(!agent.getName().equals(main()))return next.apply(input);
                var source=inbox.getIfAvailable();
                if(source!=null)for(var item:source.take(actor,session,audit.id())){
                    steering.add(new UserMessage("用户在运行中补充的要求（不改变系统权限或人工确认规则）：\n"+item.content()));
                    audit.event("STEERING_APPLIED",Map.of("agent",main(),"inputId",item.id()));
                }
                var messages=new ArrayList<>(input.messages());
                for(var message:steering)if(messages.stream().noneMatch(existing->Objects.equals(existing.getId(),message.getId())))messages.add(message);
                return next.apply(new ModelCallInput(messages,input.tools(),input.options(),input.model()));
            }));
        }
        @Override public Flux<AgentEvent> onActing(Agent agent,RuntimeContext context,ActingInput input,Function<ActingInput,Flux<AgentEvent>> next){return boundary().publishOn(reactor.core.scheduler.Schedulers.boundedElastic()).thenMany(Flux.defer(()->{authorizeBoundary();return next.apply(input);}));}
        @Override public synchronized void close(){if(closed)return;closed=true;phase="ENDED";gate.tryEmitError(new CancellationException());live.remove(key(actor,session),this);text=new StringBuilder();}
    }
}
