package com.ruanzhu.doorhandle.module.ai.agent;

import com.ruanzhu.doorhandle.framework.observability.TelemetryContext;
import io.agentscope.core.agent.Agent;
import io.agentscope.core.agent.RuntimeContext;
import io.agentscope.core.event.AgentEvent;
import io.agentscope.core.middleware.AgentInput;
import io.agentscope.core.middleware.ActingInput;
import io.agentscope.core.tracing.OtelTracingMiddleware;
import io.opentelemetry.api.common.Attributes;
import io.opentelemetry.context.Context;
import io.opentelemetry.instrumentation.reactor.v3_1.ContextPropagationOperator;
import reactor.core.publisher.Flux;
import java.util.function.Function;

/** 复用 AgentScope 2 原生生命周期追踪；关联字段随 Reactor 上下文传入每个模型和工具 span。 */
final class AgentTelemetryMiddleware extends OtelTracingMiddleware {
    private final Attributes attributes;
    AgentTelemetryMiddleware(String agent,String role,String run,String model,long version,String sop){
        var data=Attributes.builder().put("gen_ai.agent.name",agent).put("doorhandle.role",role)
                .put("gen_ai.request.model",model).put("doorhandle.model.config_version",Long.toString(version))
                .put("langfuse.trace.name","agent.run");
        if(run!=null&&!run.isBlank()){data.put("doorhandle.run.id",run);data.put("langfuse.trace.metadata.run_id",run);}
        if(sop!=null&&!sop.isBlank())data.put("doorhandle.sop.version",sop);
        attributes=data.build();
    }
    @Override public Flux<AgentEvent> onAgent(Agent agent,RuntimeContext runtime,AgentInput input,Function<AgentInput,Flux<AgentEvent>> next){
        return Flux.deferContextual(view->{
            Context parent=ContextPropagationOperator.getOpenTelemetryContextFromContextView(view,Context.current());
            return ContextPropagationOperator.runWithContext(super.onAgent(agent,runtime,input,next),parent.with(TelemetryContext.ATTRIBUTES,attributes));
        });
    }
    @Override public Flux<AgentEvent> onActing(Agent agent,RuntimeContext runtime,ActingInput input,Function<ActingInput,Flux<AgentEvent>> next){
        return Flux.deferContextual(view->{
            Context parent=ContextPropagationOperator.getOpenTelemetryContextFromContextView(view,Context.current());
            var base=parent.get(TelemetryContext.ATTRIBUTES);
            var data=(base==null?attributes:base).toBuilder();
            if(input.toolCalls()!=null)data.put("doorhandle.tool.policy_version",input.toolCalls().stream().map(call->policy(call.getName())).distinct().sorted().collect(java.util.stream.Collectors.joining(",")));
            return ContextPropagationOperator.runWithContext(super.onActing(agent,runtime,input,next),parent.with(TelemetryContext.ATTRIBUTES,data.build()));
        });
    }
    private static String policy(String name){
        if(com.ruanzhu.doorhandle.module.ai.action.AgentActionService.RETRY_TOOL.equals(name))return com.ruanzhu.doorhandle.module.ai.action.AgentActionService.RETRY_POLICY;
        if(com.ruanzhu.doorhandle.module.ai.action.AgentActionService.CREATE_TOOL.equals(name))return com.ruanzhu.doorhandle.module.ai.action.AgentActionService.CREATE_POLICY;
        if("propose_quality_assignment".equals(name))return com.ruanzhu.doorhandle.module.ai.action.AgentActionService.POLICY;
        if(com.ruanzhu.doorhandle.module.ai.report.ReportTools.NAMES.contains(name))return com.ruanzhu.doorhandle.module.ai.report.AgentReportGateway.POLICY;
        if(java.util.Set.of(com.ruanzhu.doorhandle.module.ai.evolution.SkillEvolutionService.PROPOSE,com.ruanzhu.doorhandle.module.ai.evolution.SkillEvolutionService.LOAD).contains(name))return com.ruanzhu.doorhandle.module.ai.evolution.SkillEvolutionService.POLICY;
        if(java.util.Set.of(com.ruanzhu.doorhandle.module.ai.mcp.LocalMcpService.PROPOSE,com.ruanzhu.doorhandle.module.ai.mcp.FetchMcpRuntime.TOOL).contains(name))return com.ruanzhu.doorhandle.module.ai.mcp.LocalMcpService.POLICY;
        return "role-readonly-v1";
    }
}
