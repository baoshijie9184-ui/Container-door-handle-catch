package com.ruanzhu.doorhandle.module.ai.workbench;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.agent.AgentApprovalMode;
import java.time.Duration;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeoutException;
import java.util.function.BiConsumer;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import reactor.core.publisher.Mono;
import reactor.core.publisher.Sinks;
import reactor.core.scheduler.Schedulers;

import static com.ruanzhu.doorhandle.module.ai.workbench.WorkbenchStore.fail;

/** The durable question identifies the exact in-process call. An orphaned question cannot resume a tool. */
final class ToolApprovalGate {
    static final String ALLOW = "允许本次调用";
    static final String DENY = "拒绝本次调用";
    static final List<String> OPTIONS = List.of(ALLOW, DENY);
    private static final Duration WINDOW = Duration.ofSeconds(75);
    private static final String REQUEST_NAMESPACE = "AGENT_TOOL_APPROVAL";
    private static final String MODE_NAMESPACE = "AGENT_TOOL_APPROVAL_TASK";
    private static final Set<String> INACTIVE = Set.of("NEEDS_REVIEW","CANCELLED","COMPLETED");
    private final WorkbenchStore store;
    private final Map<String,Held> active = new ConcurrentHashMap<>();

    record Invocation(String callId,String tool,String inputHash) {}
    record Request(Invocation invocation,String summary) {}
    record Held(String id,AgentActor actor,WorkbenchStore.Attempt attempt,Request request,
                long expiresAt,Sinks.One<Boolean> answer) {}

    ToolApprovalGate(WorkbenchStore store){this.store=store;}

    void captureMode(AgentActor actor,String session,String task,ConversationApprovalModes.Selection selection){
        if(selection.mode()==AgentApprovalMode.DEFAULT)return;
        store.jdbc().update("""
                INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,state_code,created_at,updated_at)
                VALUES(?,?,?,?,?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))
                """,MODE_NAMESPACE,actor.userId(),modeKey(session,task),selection.revision(),selection.mode().name());
    }

    ConversationApprovalModes.Selection mode(AgentActor actor,String session,String task){
        return store.jdbc().query("""
                SELECT state_code,revision FROM runtime_state WHERE namespace=? AND owner_id=? AND scope_key=?
                  AND legacy_clock_json IS NULL
                """,(row,index)->new ConversationApprovalModes.Selection(AgentApprovalMode.valueOf(row.getString(1)),row.getLong(2)),
                MODE_NAMESPACE,actor.userId(),modeKey(session,task)).stream().findFirst()
                .orElseGet(()->new ConversationApprovalModes.Selection(AgentApprovalMode.DEFAULT,0));
    }

    private static String modeKey(String session,String task){return WorkbenchStore.hash(session.length()+":"+session+":"+task);}

    Mono<Void> await(AgentActor actor,WorkbenchStore.Attempt attempt,List<Request> calls,
                     BiConsumer<String,Held> audit){
        if(calls.isEmpty())return Mono.empty();
        if(calls.size()>16||new HashSet<>(calls.stream().map(call->call.invocation().callId()).toList()).size()!=calls.size())
            return Mono.error(fail(403,"工具调用批次编号或数量不合法"));
        return Mono.usingWhen(Mono.fromCallable(()->open(actor,attempt,calls)).subscribeOn(Schedulers.boundedElastic()),
                held->Mono.defer(()->{
                    held.forEach(request->audit.accept("TOOL_APPROVAL_REQUIRED",request));
                    return Mono.when(held.stream().map(request->request.answer().asMono().publishOn(Schedulers.boundedElastic()).flatMap(approved->{
                        audit.accept(approved?"TOOL_APPROVAL_APPROVED":"TOOL_APPROVAL_REJECTED",request);
                        return approved?Mono.empty():Mono.error(new AgentWorkbenchService.ToolApprovalStopped("已拒绝工具调用，本批工具尚未执行。"));
                    })).toList());
                }).timeout(WINDOW).onErrorMap(TimeoutException.class,error->new AgentWorkbenchService.ToolApprovalStopped("工具审批已超时，本批工具尚未执行。")),
                held->cleanup(held,audit),(held,error)->cleanup(held,audit),held->cleanup(held,audit));
    }

    private List<Held> open(AgentActor actor,WorkbenchStore.Attempt attempt,List<Request> calls){
        long expires=System.nanoTime()+WINDOW.toNanos();
        var batch=calls.stream().map(call->new Held(UUID.randomUUID().toString(),actor,attempt,call,expires,Sinks.one())).toList();
        try {
            return store.withAttempt(attempt,()->{
                for(var request:batch){
                    active.put(request.id(),request);
                    store.jdbc().update("""
                            INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,state_code,current_ref,created_at,updated_at)
                            VALUES(?,?,?,1,'OPEN',?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))
                            """,REQUEST_NAMESPACE,actor.userId(),request.id(),attempt.runId());
                    store.create(actor.userId(),attempt.session(),request.id(),"QUESTION","PENDING",Map.of(
                            "parentId",attempt.itemId(),"runId",attempt.runId(),"logicalTaskId",attempt.taskId(),
                            "questionType","SINGLE","options",OPTIONS,"text","工具调用待确认："+request.request().invocation().tool()
                                    +request.request().summary()+"。批准只适用于本次调用，账号与业务权限仍会重新检查。"));
                }
                return batch;
            });
        }catch(RuntimeException failure){batch.forEach(request->active.remove(request.id(),request));throw failure;}
    }

    boolean isToolQuestion(WorkbenchStore.Row row){
        return row.kind().equals("QUESTION")&&store.jdbc().queryForObject("""
                SELECT COUNT(*) FROM runtime_state WHERE namespace=? AND owner_id=? AND scope_key=? AND current_ref=?
                """,Long.class,REQUEST_NAMESPACE,row.user(),row.id(),row.data().get("runId"))>0;
    }

    void requireLive(AgentActor actor,WorkbenchStore.Row row,WorkbenchStore.Row parent){
        var request=active.get(row.id());
        if(request==null||!request.actor().equals(actor)||System.nanoTime()-request.expiresAt()>=0
                ||!Objects.equals(request.attempt(),store.attempt(parent))
                ||!Objects.equals(request.attempt().runId(),row.data().get("runId"))
                ||!Objects.equals(request.attempt().taskId(),row.data().get("logicalTaskId")))
            throw fail(409,"原工具调用已结束或过期，请重新发起请求");
        store.assertAttempt(request.attempt());
    }

    void signal(AgentActor actor,String session,String question,Object answer){
        var request=active.get(question);
        if(request==null||!request.actor().equals(actor)||!request.attempt().session().equals(session))return;
        Runnable publish=()->request.answer().tryEmitValue(ALLOW.equals(answer));
        if(TransactionSynchronizationManager.isSynchronizationActive())
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization(){@Override public void afterCommit(){publish.run();}});
        else publish.run();
    }

    private Mono<Void> cleanup(List<Held> requests,BiConsumer<String,Held> audit){
        return Mono.<Void>fromRunnable(()->{
            for(var request:requests){
                active.remove(request.id(),request);
                var attempt=request.attempt();
                boolean closed=store.locked(attempt.user(),()->{
                    var row=store.require(attempt.user(),attempt.session(),request.id());
                    boolean pending="PENDING".equals(row.status());
                    if(pending)store.update(row,"CANCELLED",row.data(),"TOOL_APPROVAL_CANCELLED");
                    store.jdbc().update("UPDATE runtime_state SET state_code='CLOSED',updated_at=UTC_TIMESTAMP(6) WHERE namespace=? AND owner_id=? AND scope_key=?",
                            REQUEST_NAMESPACE,attempt.user(),request.id());
                    return pending;
                });
                if(closed)audit.accept("TOOL_APPROVAL_CANCELLED",request);
            }
        }).subscribeOn(Schedulers.boundedElastic());
    }

    void closeOrphans(WorkbenchStore.Row execution){
        if(!INACTIVE.contains(execution.status()))return;
        store.locked(execution.user(),()->{
            for(var row:store.pendingInteractions(execution.user(),execution.session(),execution.id(),execution.data().get("logicalTaskId"))){
                if(isToolQuestion(row))store.update(row,"CANCELLED",row.data(),"TOOL_APPROVAL_CANCELLED");
            }
            store.jdbc().update("UPDATE runtime_state SET state_code='CLOSED',updated_at=UTC_TIMESTAMP(6) WHERE namespace=? AND owner_id=? AND current_ref=? AND state_code='OPEN'",
                    REQUEST_NAMESPACE,execution.user(),execution.data().get("runId"));
            return null;
        });
    }

}
