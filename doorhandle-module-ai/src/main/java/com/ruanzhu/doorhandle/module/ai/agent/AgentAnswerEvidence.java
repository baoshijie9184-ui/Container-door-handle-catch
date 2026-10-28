package com.ruanzhu.doorhandle.module.ai.agent;

import io.agentscope.core.agent.Agent;
import io.agentscope.core.agent.RuntimeContext;
import io.agentscope.core.event.AgentEvent;
import io.agentscope.core.event.ToolResultEndEvent;
import io.agentscope.core.middleware.ActingInput;
import io.agentscope.core.middleware.MiddlewareBase;
import reactor.core.publisher.Flux;

import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Function;
import java.util.regex.Pattern;

/** Per-attempt evidence only. Never initiates a tool or repeats a model request. */
public final class AgentAnswerEvidence implements MiddlewareBase {
    private static final Pattern HANDOFF_CLAIM = Pattern.compile(
            "(?:^|[。！？])\\s*(?:好的[，,。\\s]*)?(?:(?:我(?:将|会|现在|这就)|接下来(?:将|会)|正在|已经|已)"
                    + "(?:为你|为您|帮你|帮您)?[\\s，,:：]*(?:委派|委托|转交|交给|派给)"
                    + "|(?:I\\s+(?:will|am going to|have)|I['’]ll)\\s+(?:delegate|hand\\s+off)\\b)",
            Pattern.CASE_INSENSITIVE | Pattern.MULTILINE);
    private final Set<String> completedHandoffs = ConcurrentHashMap.newKeySet();

    @Override
    public Flux<AgentEvent> onActing(Agent agent, RuntimeContext context, ActingInput input,
                                     Function<ActingInput, Flux<AgentEvent>> next) {
        return Flux.defer(() -> next.apply(input).doOnNext(event -> {
            if (event instanceof ToolResultEndEvent end && end.getState() != null
                    && "SUCCESS".equals(end.getState().name())) {
                String tool = end.getToolCallName();
                if (tool != null && (tool.startsWith("delegate_") || tool.equals("start_background_task"))) {
                    completedHandoffs.add(tool);
                }
            }
        }));
    }

    public boolean unsupportedHandoff(String text) {
        return text != null && completedHandoffs.isEmpty() && HANDOFF_CLAIM.matcher(text).find();
    }
}
