package com.ruanzhu.doorhandle.module.app.stategraph.core;

import com.ruanzhu.doorhandle.module.app.stategraph.node.FallbackNode;
import org.junit.jupiter.api.Test;

import java.util.concurrent.atomic.AtomicReference;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class CompiledGraphGuardTest {

    @Test
    void shouldRecordNodeTraceForNormalExecution() {
        CompiledGraph graph = new StateGraph()
                .addNode("answer", state -> state
                        .set(AgentState.KEY_RESULT_CONTENT, "ok")
                        .set(AgentState.KEY_RESULT_TYPE, "TEXT")
                        .set(AgentState.KEY_EXIT_REASON, AgentState.EXIT_COMPLETE))
                .setEntryPoint("answer")
                .compile();

        AgentState result = graph.invoke(AgentState.create("sess_guard_1", "hi", "admin"));

        assertThat(result.get(AgentState.KEY_NODE_TRACE, List.class)).containsExactly("answer");
        assertThat(result.getString(AgentState.KEY_EXIT_REASON)).isEqualTo(AgentState.EXIT_COMPLETE);
    }

    @Test
    void shouldBreakSelfLoopAndFallbackWithGuardReason() {
        CompiledGraph graph = new StateGraph()
                .addNode("loop", state -> state.set(AgentState.KEY_NEXT_NODE, "loop"))
                .addNode("fallback", new FallbackNode())
                .setEntryPoint("loop")
                .setFallbackNode("fallback")
                .setMaxIterations(20)
                .compile();

        AgentState result = graph.invoke(AgentState.create("sess_guard_2", "loop please", "admin"));

        assertThat(result.getString(AgentState.KEY_EXIT_REASON)).isEqualTo(AgentState.EXIT_GUARD_BREAK);
        assertThat(result.getString(AgentState.KEY_GUARD_REASON)).contains("重复");
        assertThat(result.getString(AgentState.KEY_RESULT_CONTENT)).contains("保护性中断");
        assertThat(result.get(AgentState.KEY_NODE_TRACE, List.class)).contains("loop");
        assertThat(result.get(AgentState.KEY_ROUTE_TRACE, List.class)).contains("loop->loop");
    }

    @Test
    void shouldUseConfiguredRouteRepeatLimit() {
        com.ruanzhu.doorhandle.module.app.config.properties.AgentGraphGuardProperties properties =
                new com.ruanzhu.doorhandle.module.app.config.properties.AgentGraphGuardProperties();
        properties.setMaxRepeatRoute(1);

        CompiledGraph graph = new StateGraph()
                .addNode("loop", state -> state.set(AgentState.KEY_NEXT_NODE, "loop"))
                .addNode("fallback", new FallbackNode())
                .setEntryPoint("loop")
                .setFallbackNode("fallback")
                .setGuardProperties(properties)
                .compile();

        AgentState result = graph.invoke(AgentState.create("sess_guard_3", "loop please", "admin"));

        assertThat(result.getString(AgentState.KEY_EXIT_REASON)).isEqualTo(AgentState.EXIT_GUARD_BREAK);
        assertThat(result.getInt(AgentState.KEY_ITERATION)).isEqualTo(2);
        assertThat(result.getInt(AgentState.KEY_ROUTE_REPEAT_COUNT)).isEqualTo(2);
    }

    @Test
    void shouldNotifyRunListenerWhenExecutionFinishes() {
        AtomicReference<AgentState> observed = new AtomicReference<>();
        CompiledGraph graph = new StateGraph()
                .addNode("answer", state -> state
                        .set(AgentState.KEY_RESULT_CONTENT, "ok")
                        .set(AgentState.KEY_EXIT_REASON, AgentState.EXIT_COMPLETE))
                .setEntryPoint("answer")
                .setRunListener(observed::set)
                .compile();

        AgentState result = graph.invoke(AgentState.create("sess_guard_4", "hi", "admin"));

        assertThat(observed.get()).isSameAs(result);
        assertThat(observed.get().getString(AgentState.KEY_EXIT_REASON)).isEqualTo(AgentState.EXIT_COMPLETE);
    }
}
