package com.ruanzhu.doorhandle.module.app.service.impl;

import com.ruanzhu.doorhandle.module.app.dto.chat.AgentGraphHealthResponse;
import com.ruanzhu.doorhandle.module.app.stategraph.core.AgentState;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AgentGraphRunMonitorImplTest {

    @Test
    void shouldCountRunOutcomesAndSnapshotHealth() {
        SimpleMeterRegistry meterRegistry = new SimpleMeterRegistry();
        AgentGraphRunMonitorImpl monitor = new AgentGraphRunMonitorImpl(meterRegistry);

        monitor.onRunFinished(AgentState.create("sess_1", "hi", "admin")
                .set(AgentState.KEY_EXIT_REASON, AgentState.EXIT_COMPLETE)
                .set(AgentState.KEY_GUARD_ELAPSED_MS, 10));
        monitor.onRunFinished(AgentState.create("sess_2", "loop", "admin")
                .set(AgentState.KEY_EXIT_REASON, AgentState.EXIT_GUARD_BREAK)
                .set(AgentState.KEY_GUARD_REASON, "路由重复跳转次数过多")
                .set(AgentState.KEY_INTENT, "FALLBACK")
                .set(AgentState.KEY_GUARD_ELAPSED_MS, 20));

        AgentGraphHealthResponse snapshot = monitor.snapshot();

        assertThat(snapshot.getTotalRuns()).isEqualTo(2);
        assertThat(snapshot.getCompletedRuns()).isEqualTo(1);
        assertThat(snapshot.getGuardBreakRuns()).isEqualTo(1);
        assertThat(snapshot.getFallbackRuns()).isEqualTo(1);
        assertThat(snapshot.getAverageElapsedMs()).isEqualTo(15);
        assertThat(snapshot.getGuardBreakRate()).isEqualTo(0.5);
        assertThat(snapshot.getFallbackRate()).isEqualTo(0.5);
        assertThat(snapshot.getHealthStatus()).isEqualTo("CRITICAL");
        assertThat(snapshot.getLastGuardReason()).isEqualTo("路由重复跳转次数过多");
        assertThat(meterRegistry.counter("agent.graph.runs", "exit_reason", "COMPLETE", "intent", "UNKNOWN").count())
                .isEqualTo(1.0);
        assertThat(meterRegistry.counter("agent.graph.runs", "exit_reason", "GUARD_BREAK", "intent", "FALLBACK").count())
                .isEqualTo(1.0);
        assertThat(meterRegistry.find("agent.graph.run.elapsed").timers()).hasSize(2);
    }
}
