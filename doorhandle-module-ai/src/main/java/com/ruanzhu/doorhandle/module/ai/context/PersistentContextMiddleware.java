package com.ruanzhu.doorhandle.module.ai.context;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.agent.AgentContextDataApi.Source;
import static com.ruanzhu.doorhandle.contracts.agent.AgentContextDataApi.RETRIEVAL_POLICY_V2;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import com.ruanzhu.doorhandle.module.ai.workbench.AgentWorkbenchService;
import io.agentscope.core.ReActAgent;
import io.agentscope.core.agent.*;
import io.agentscope.core.event.AgentEvent;
import io.agentscope.core.message.*;
import io.agentscope.core.middleware.*;
import io.agentscope.core.model.Model;
import reactor.core.publisher.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.*;

/** Authorizes model history and checkpoints independently from optional compaction. */
public final class PersistentContextMiddleware implements MiddlewareBase {
    private static final int MAX_RECENT_MESSAGES=38;
    private final DurableContextStore store;private final AgentWorkbenchService.Scope scope;private final AgentActor actor;
    private final String session,key,runtimeKey;private final AgentContextCompaction compactor;private final DurableContextStore.Bootstrap boot;
    private final AtomicBoolean initialized;
    private final Set<Source> seedSources=new LinkedHashSet<>();
    public PersistentContextMiddleware(DurableContextStore store,AgentWorkbenchService.Scope scope,ContextCompactionSettings settings,Model model,BiConsumer<String,Map<String,Object>> recorder){
        this.store=store;this.scope=scope;actor=scope.contextActor();session=scope.contextSession();key=scope.contextKey();runtimeKey=key.equals("main")?"task:"+scope.contextTask():key;
        boolean restoring=scope.restoringContext();
        if(restoring)store.assertCheckpointReadable(actor,session,key,scope.contextTask());
        else {
            var sources=scope.initialContextSources();
            if(!sources.isEmpty()&&!store.authorized(actor,session,sources)) {
                throw new ResponseStatusException(HttpStatus.CONFLICT,"本轮参考资料的权限或版本已变化，请重新发起");
            }
            seedSources.addAll(sources);
        }
        seedSources.add(RETRIEVAL_POLICY_V2);
        boot=store.bootstrap(actor,session,key,scope.contextTask(),scope.initialContextMessages());
        initialized=new AtomicBoolean(boot.ready());
        compactor=settings.isEnabled()?new AgentContextCompaction(settings,model,recorder):null;
        if(boot.ready()&&!restoring)throw new IllegalStateException("原执行检查点缺失，不能仅凭摘要重放任务");
    }
    @Override public Flux<AgentEvent> onReasoning(Agent agent,RuntimeContext context,ReasoningInput input,Function<ReasoningInput,Flux<AgentEvent>> next){return Flux.defer(()->{
        if(!(agent instanceof ReActAgent react))return Flux.error(new IllegalStateException("持久上下文需要 SDK 状态支持"));
        var state=RuntimeContext.resolveAgentState(context==null?RuntimeContext.empty():context,react);if(state==null)return Flux.error(new IllegalStateException("上下文状态不可用"));
        var system=input.messages().stream().filter(m->m.getRole()==MsgRole.SYSTEM).toList();var conversation=input.messages().stream().filter(m->m.getRole()!=MsgRole.SYSTEM).toList();
        Mono<List<Msg>> prepared;
        if(initialized.get()){store.assertTaskReadable(actor,session,scope.contextTask());store.validateMessages(actor,session,new HashSet<>(List.of(key,runtimeKey)),conversation);prepared=Mono.just(conversation);}
        else{
            Mono<List<Msg>> prefix=key.equals("main")?history(context,agent.getName()):Mono.just(List.of());
            prepared=prefix.map(previous->{var messages=new ArrayList<>(previous);messages.addAll(boot.initial());
                List<Msg> current=conversation;
                int shared=0;while(shared<current.size()&&shared<boot.initial().size()&&Objects.equals(current.get(shared).getTextContent(),boot.initial().get(shared).getTextContent()))shared++;
                messages.addAll(current.subList(shared,current.size()));
                state.contextMutable().clear();state.contextMutable().addAll(messages);
                seedSources.addAll(store.collect(messages));seedSources.addAll(store.inheritedSources(actor,session,messages));
                store.initialized(actor,session,key,scope.contextTask(),()->{store.recordSeed(actor,session,key,scope.contextTask(),scope.runId(),List.copyOf(seedSources));scope.persistContext(agent,context);});initialized.set(true);return List.copyOf(messages);
            });
        }
        if(compactor!=null)prepared=prepared.flatMap(messages->{
            var prior=store.load(actor,session,runtimeKey);long expected=prior==null?store.revision(actor,session,runtimeKey):prior.revision();
            return compactor.compact(context,messages,agent.getName(),candidate->{
            var refs=new ArrayList<Source>(store.collect(messages.subList(0,candidate.cutoff())));refs.addAll(store.inheritedSources(actor,session,messages.subList(0,candidate.cutoff())));refs.addAll(store.taskSources(actor,session,scope.contextTask()));if(prior!=null)refs.addAll(prior.sources());
            long covered=(prior==null?0:prior.covered())+candidate.cutoff()-(prior==null?0:1);
            var saved=store.save(actor,session,runtimeKey,scope.runId(),expected,covered,DurableContextStore.hash(store.write(messages.stream().map(Msg::getTextContent).toList())),candidate.summary(),candidate.messages().get(0),refs,messages.subList(0,candidate.cutoff()));
            candidate.messages().set(0,saved.message());
        }).map(result->result.isPresent()?result.get().messages():messages);});
        return prepared.flatMapMany(messages->{
            store.assertTaskReadable(actor,session,scope.contextTask());store.validateMessages(actor,session,new HashSet<>(List.of(key,runtimeKey)),messages);state.contextMutable().clear();state.contextMutable().addAll(messages);
            var actual=new ArrayList<>(system);actual.addAll(messages);return next.apply(new ReasoningInput(actual,input.tools(),input.options()));
        });
    });}
    private Mono<List<Msg>> history(RuntimeContext context,String agent){
        if(boot.through()==0)return Mono.just(List.of());
        if(compactor==null){
            var recent=store.data().recentHistory(actor,session,boot.through(),MAX_RECENT_MESSAGES);
            return Mono.just(projectHistory(recent.messages().stream().filter(entry->entry.text().length()<=8000).toList())
                    .stream().map(PersistentContextMiddleware::message).toList());
        }
        var summary=store.load(actor,session,"main");
        if(summary!=null&&(!summary.sources().contains(RETRIEVAL_POLICY_V2)
                ||!store.data().historyDigest(actor,session,summary.covered()).equals(summary.historyHash()))){store.invalidate(actor,session,"main",summary.id());summary=null;}
        if(summary!=null)seedSources.addAll(summary.sources());
        return page(context,agent,summary,new ArrayList<>(),summary==null?0:summary.covered(),0);
    }
    private List<AgentContextDataApi.Message> projectHistory(List<AgentContextDataApi.Message> history){
        var entries=new ArrayList<AgentContextDataApi.Message>(history.size());
        for(var message:history){
            var refs=new ArrayList<>(message.sources());var linked=store.turnSources(actor,session,message.id());if(linked!=null)refs.addAll(linked);
            String text=message.text();
            if(message.role().equals("assistant")&&(linked==null||!linked.contains(RETRIEVAL_POLICY_V2))){
                text="[此段旧回答没有可验证的工具和检索来源记录；原文保留在聊天记录，关键业务事实请重新查询]";
                refs.clear();
            }
            if(!store.authorized(actor,session,refs)){text="[历史资料授权已变化，此段不作为本轮上下文依据]";refs.clear();}
            seedSources.addAll(refs);
            entries.add(new AgentContextDataApi.Message(message.id(),message.role(),text,List.copyOf(refs)));
        }
        return entries;
    }
    private static Msg message(AgentContextDataApi.Message entry){
        return entry.role().equals("user")?new UserMessage(entry.text()):new AssistantMessage(entry.text());
    }
    private Mono<List<Msg>> page(RuntimeContext context,String agent,DurableContextStore.Summary previous,List<AgentContextDataApi.Message> tail,long after,int pages){return Mono.defer(()->{
        if(pages>=32)throw new IllegalStateException("历史重建超过本轮资源上限，未省略历史后继续");
        String anchorHash=store.data().historyDigest(actor,session,boot.through());long expected=previous==null?store.revision(actor,session,"main"):previous.revision();
        var page=store.data().history(actor,session,after,boot.through(),128);var entries=new ArrayList<>(tail);
        entries.addAll(projectHistory(page.messages()));
        var messages=new ArrayList<Msg>();if(previous!=null)messages.add(previous.message());for(var entry:entries)messages.add(message(entry));
        var saved=new java.util.concurrent.atomic.AtomicReference<>(previous);var consumed=new java.util.concurrent.atomic.AtomicInteger();
        return compactor.compact(context,messages,agent,candidate->{
            int count=candidate.cutoff()-(previous==null?0:1);if(count<=0||count>entries.size())throw new IllegalStateException("摘要历史切点无法映射");
            long covered=entries.get(count-1).id();var refs=new ArrayList<Source>();refs.add(RETRIEVAL_POLICY_V2);if(previous!=null)refs.addAll(previous.sources());for(var entry:entries.subList(0,count))refs.addAll(entry.sources());
            if(!anchorHash.equals(store.data().historyDigest(actor,session,boot.through())))throw new IllegalStateException("原始历史已变化，停止应用当前摘要");
            var next=store.save(actor,session,"main",scope.runId(),expected,covered,store.data().historyDigest(actor,session,covered),candidate.summary(),candidate.messages().get(0),refs,messages.subList(0,candidate.cutoff()));
            candidate.messages().set(0,next.message());saved.set(next);consumed.set(count);
        }).flatMap(result->{
            var remaining=entries.subList(consumed.get(),entries.size());
            if(page.hasMore()){
                if(remaining.size()>256)throw new IllegalStateException("摘要预算不足，原始历史已保留，未截断后继续");
                return page(context,agent,saved.get(),List.copyOf(remaining),page.messages().get(page.messages().size()-1).id(),pages+1);
            }
            var finalMessages=new ArrayList<Msg>();if(saved.get()!=null)finalMessages.add(saved.get().message());for(var entry:remaining)finalMessages.add(message(entry));
            if(finalMessages.size()>256||DurableContextStore.characters(finalMessages)>1000000)throw new IllegalStateException("上下文重建超出本轮预算，未省略后继续");
            return Mono.just(List.copyOf(finalMessages));
        });
    });}
}
