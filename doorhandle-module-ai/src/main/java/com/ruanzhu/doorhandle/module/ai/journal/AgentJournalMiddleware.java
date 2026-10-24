package com.ruanzhu.doorhandle.module.ai.journal;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.module.ai.agent.RoleAgentCatalog;
import io.agentscope.core.agent.*;
import io.agentscope.core.event.*;
import io.agentscope.core.middleware.*;
import org.springframework.security.access.AccessDeniedException;
import reactor.core.publisher.Flux;
import reactor.core.publisher.SignalType;
import java.util.*;
import java.util.function.Function;

/** 复用 SDK 中间件生命周期；不采集提示词、参数、结果正文或思考内容。 */
public class AgentJournalMiddleware implements MiddlewareBase {
    private final AgentJournal.Run run;
    private final AgentActor actor;
    private final long began;
    private final String parentCallId;
    private final boolean confirmation;
    private final boolean reports,drafts;
    private com.ruanzhu.doorhandle.module.ai.evolution.SkillEvolutionService evolution;
    private com.ruanzhu.doorhandle.module.ai.mcp.LocalMcpService mcp;
    private Set<String> workbenchTools=Set.of();
    private boolean detectionRetry, detectionCreation;
    public AgentJournalMiddleware withDetectionCreation(boolean enabled){detectionCreation=enabled;return this;}
    public AgentJournalMiddleware withDetectionRetry(boolean enabled){detectionRetry=enabled;return this;}
    public AgentJournalMiddleware withWorkbench(Set<String> tools){this.workbenchTools=Set.copyOf(tools);return this;}
    public AgentJournalMiddleware(AgentJournal.Run run,AgentActor actor) { this(run,actor,false); }
    public AgentJournalMiddleware(AgentJournal.Run run,AgentActor actor,boolean confirmation) {this(run,actor,confirmation,false,false);}
    public AgentJournalMiddleware(AgentJournal.Run run,AgentActor actor,boolean confirmation,boolean reports,boolean drafts){this(run,actor,System.nanoTime(),null,confirmation,reports,drafts);}
    private AgentJournalMiddleware(AgentJournal.Run run,AgentActor actor,long began,String parentCallId,boolean confirmation,boolean reports,boolean drafts) {
        this.run=run;this.actor=actor;this.began=began;this.parentCallId=parentCallId;this.confirmation=confirmation;this.reports=reports;this.drafts=drafts;
    }
    public AgentJournalMiddleware child(String callId) { var child=new AgentJournalMiddleware(run,actor,began,identifier(callId),confirmation,reports,drafts);child.evolution=evolution;child.mcp=mcp;child.detectionRetry=detectionRetry;child.detectionCreation=detectionCreation;return child; }
    public AgentJournalMiddleware withEvolution(com.ruanzhu.doorhandle.module.ai.evolution.SkillEvolutionService service){var next=new AgentJournalMiddleware(run,actor,began,parentCallId,confirmation,reports,drafts);next.evolution=service;next.mcp=mcp;next.detectionRetry=detectionRetry;next.detectionCreation=detectionCreation;return next;}
    public AgentJournalMiddleware withMcp(com.ruanzhu.doorhandle.module.ai.mcp.LocalMcpService service){var next=new AgentJournalMiddleware(run,actor,began,parentCallId,confirmation,reports,drafts);next.evolution=evolution;next.mcp=service;next.detectionRetry=detectionRetry;next.detectionCreation=detectionCreation;return next;}
    public String runId() { return run.id(); }
    public void recordContext(String type,Map<String,Object> metadata){var payload=fields((String)metadata.get("agent"));payload.putAll(metadata);run.event(type,payload);}
    private Map<String,Object> fields(String agent) {
        var result=new LinkedHashMap<String,Object>();result.put("agent",agent);
        result.put("elapsedMs",(System.nanoTime()-began)/1_000_000);if(parentCallId!=null)result.put("parentCallId",parentCallId);return result;
    }
    @Override public Flux<AgentEvent> onAgent(Agent agent,RuntimeContext context,AgentInput input,Function<AgentInput,Flux<AgentEvent>> next) {
        return Flux.defer(()->{
            long start=System.nanoTime();run.event("AGENT_STARTED",fields(agent.getName()));
            var terminal=new java.util.concurrent.atomic.AtomicBoolean();
            return next.apply(input).doOnComplete(()->{if(terminal.compareAndSet(false,true))run.event("AGENT_COMPLETED",duration(agent,start));})
                .doOnError(error->{if(terminal.compareAndSet(false,true))run.event(yielded(error)?"AGENT_YIELDED":"AGENT_ERROR",duration(agent,start));})
                .doFinally(signal->{if(signal==SignalType.CANCEL&&terminal.compareAndSet(false,true))recordCancellation("AGENT_CANCELLED",duration(agent,start));});
        });
    }
    @Override public Flux<AgentEvent> onModelCall(Agent agent,RuntimeContext context,ModelCallInput input,Function<ModelCallInput,Flux<AgentEvent>> next) {
        return Flux.defer(()->{
            long start=System.nanoTime();
            String requestId=UUID.randomUUID().toString();
            var initial=fields(agent.getName());initial.put("modelRequestId",requestId);run.event("MODEL_STARTED",initial);
            var trace=new com.ruanzhu.doorhandle.module.ai.model.ModelAttemptTrace((type,metadata)->{
                var payload=fields(agent.getName());payload.putAll(metadata);payload.put("modelRequestId",requestId);run.event(type,payload);
            });
            return Flux.defer(()->next.apply(input)).doOnNext(event->{
                if(event instanceof ModelCallEndEvent end) {
                    var payload=duration(agent,start);payload.put("modelRequestId",requestId);
                    if(end.getUsage()!=null) {payload.put("inputTokens",Math.max(0,end.getUsage().getInputTokens()));payload.put("outputTokens",Math.max(0,end.getUsage().getOutputTokens()));}
                    run.event("MODEL_COMPLETED",payload);
                }
            }).doOnError(error->{var payload=duration(agent,start);payload.put("modelRequestId",requestId);run.event(yielded(error)?"MODEL_YIELDED":"MODEL_ERROR",payload);})
              .doFinally(signal->{if(signal==SignalType.CANCEL){var payload=duration(agent,start);payload.put("modelRequestId",requestId);recordCancellation("MODEL_CANCELLED",payload);}})
              .contextWrite(contextValue->contextValue.put(com.ruanzhu.doorhandle.module.ai.model.ModelAttemptTrace.CONTEXT_KEY,trace));
        });
    }
    @Override public Flux<AgentEvent> onActing(Agent agent,RuntimeContext context,ActingInput input,Function<ActingInput,Flux<AgentEvent>> next) {
        return Flux.defer(()->{
            var allowed=new HashSet<String>();
            allowed.addAll(workbenchTools);
            if(agent.getName().equals(RoleAgentCatalog.mainId(actor))) {
                RoleAgentCatalog.specialists(actor,confirmation,reports,drafts,detectionRetry,detectionCreation).forEach(def->allowed.add("delegate_"+def.id().replace('-','_')));
                if(evolution!=null){allowed.add(com.ruanzhu.doorhandle.module.ai.evolution.SkillEvolutionService.PROPOSE);allowed.add(com.ruanzhu.doorhandle.module.ai.evolution.SkillEvolutionService.LOAD);if(evolution.linksEnabled())allowed.add(com.ruanzhu.doorhandle.module.ai.evolution.SkillLinkProposalTool.NAME);}
                if(mcp!=null){allowed.add(com.ruanzhu.doorhandle.module.ai.mcp.LocalMcpService.PROPOSE);if(mcp.available(actor))allowed.add(com.ruanzhu.doorhandle.module.ai.mcp.FetchMcpRuntime.TOOL);}
            } else RoleAgentCatalog.specialists(actor,confirmation,reports,drafts,detectionRetry,detectionCreation).stream().filter(def->def.id().equals(agent.getName())).forEach(def->allowed.addAll(def.tools()));
            for(var call:input.toolCalls()) {
                var payload=fields(agent.getName());payload.put("callId",identifier(call.getId()));
                boolean permitted=allowed.contains(call.getName());
                payload.put("tool",permitted?call.getName():"unregistered");
                payload.put("decision",permitted?"ALLOW":"DENY");payload.put("policyVersion","propose_quality_assignment".equals(call.getName())?com.ruanzhu.doorhandle.module.ai.action.AgentActionService.POLICY:com.ruanzhu.doorhandle.module.ai.report.ReportTools.NAMES.contains(call.getName())?com.ruanzhu.doorhandle.module.ai.report.AgentReportGateway.POLICY:"role-readonly-v1");
                if(com.ruanzhu.doorhandle.module.ai.action.AgentActionService.RETRY_TOOL.equals(call.getName()))payload.put("policyVersion",com.ruanzhu.doorhandle.module.ai.action.AgentActionService.RETRY_POLICY);
                if(com.ruanzhu.doorhandle.module.ai.action.AgentActionService.CREATE_TOOL.equals(call.getName()))payload.put("policyVersion",com.ruanzhu.doorhandle.module.ai.action.AgentActionService.CREATE_POLICY);
                payload.put("scope",actor.supervisor()?"SINGLE_ENTERPRISE":"OWNED_OR_ASSIGNED");
                if(Set.of(com.ruanzhu.doorhandle.module.ai.evolution.SkillEvolutionService.PROPOSE,com.ruanzhu.doorhandle.module.ai.evolution.SkillEvolutionService.LOAD).contains(call.getName()))payload.put("policyVersion",com.ruanzhu.doorhandle.module.ai.evolution.SkillEvolutionService.POLICY);
                if(Set.of(com.ruanzhu.doorhandle.module.ai.mcp.LocalMcpService.PROPOSE,com.ruanzhu.doorhandle.module.ai.mcp.FetchMcpRuntime.TOOL).contains(call.getName())){payload.put("policyVersion",com.ruanzhu.doorhandle.module.ai.mcp.LocalMcpService.POLICY);payload.put("scope","USER_PRIVATE_MCP_PUBLIC_WEB");}
                run.event(permitted?"AUTHORIZATION_ALLOWED":"AUTHORIZATION_DENIED",payload);
                if(!permitted)throw new AccessDeniedException("工具没有当前角色权限");
                if(evolution!=null&&com.ruanzhu.doorhandle.module.ai.evolution.SkillEvolutionService.LOAD.equals(call.getName()))evolution.assertReadable(actor,call.getInput());
                if(mcp!=null&&com.ruanzhu.doorhandle.module.ai.mcp.FetchMcpRuntime.TOOL.equals(call.getName()))mcp.assertEnabled(actor,call.getInput());
                run.event("TOOL_STARTED",payload);
            }
            long start=System.nanoTime();
            return next.apply(input).doOnNext(event->{
                if(event instanceof ToolResultEndEvent end) {
                    var payload=duration(agent,start);payload.put("tool",allowed.contains(end.getToolCallName())?end.getToolCallName():"unregistered");
                    payload.put("callId",identifier(end.getToolCallId()));
                    String state=end.getState()==null?"UNKNOWN":end.getState().name();payload.put("result",state);
                    run.event("SUCCESS".equals(state)?"TOOL_COMPLETED":"TOOL_ERROR",payload);
                    if(evolution!=null&&"SUCCESS".equals(state)&&com.ruanzhu.doorhandle.module.ai.evolution.SkillEvolutionService.LOAD.equals(end.getToolCallName())) {
                        input.toolCalls().stream().filter(call->Objects.equals(call.getId(),end.getToolCallId())).findFirst().ifPresent(call->evolution.recordUse(actor,(String)call.getInput().get("skillId"),run.id(),end.getToolCallId()));
                    }
                }
            }).doOnError(error->{ for(var call:input.toolCalls()) {var payload=duration(agent,start);payload.put("tool",call.getName());payload.put("callId",identifier(call.getId()));run.event("TOOL_ERROR",payload);} })
              .doFinally(signal->{if(signal==SignalType.CANCEL)for(var call:input.toolCalls()){var payload=duration(agent,start);payload.put("tool",call.getName());payload.put("callId",identifier(call.getId()));recordCancellation("TOOL_CANCELLED",payload);}});
        });
    }
    private Map<String,Object> duration(Agent agent,long start) {var payload=fields(agent.getName());payload.put("durationMs",(System.nanoTime()-start)/1_000_000);return payload;}
    private static boolean yielded(Throwable error){return reactor.core.Exceptions.unwrap(error) instanceof com.ruanzhu.doorhandle.module.ai.workbench.AgentWorkbenchService.Yield;}
    private void recordCancellation(String type,Map<String,Object> payload) {
        // 运行的取消终态可能已先提交；迟到的取消钩子不能改变终态。
        try{run.event(type,payload);}catch(IllegalStateException ignored){}
    }
    private static String identifier(String value) {
        if(value!=null&&value.matches("[A-Za-z0-9_:.-]{1,160}"))return value;
        return "sdk-"+UUID.nameUUIDFromBytes(Objects.toString(value,"").getBytes(java.nio.charset.StandardCharsets.UTF_8));
    }
}
