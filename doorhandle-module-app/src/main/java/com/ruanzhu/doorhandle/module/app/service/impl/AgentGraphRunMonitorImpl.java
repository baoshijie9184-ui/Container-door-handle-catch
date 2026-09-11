package com.ruanzhu.doorhandle.module.app.service.impl;

import com.ruanzhu.doorhandle.module.app.dto.chat.AgentGraphHealthResponse;
import com.ruanzhu.doorhandle.module.app.service.AgentGraphRunMonitor;
import com.ruanzhu.doorhandle.module.app.stategraph.core.AgentState;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

@Service
public class AgentGraphRunMonitorImpl implements AgentGraphRunMonitor {

    private static final DateTimeFormatter TIME_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final AtomicLong totalRuns = new AtomicLong();
    private final AtomicLong completedRuns = new AtomicLong();
    private final AtomicLong pendingConfirmationRuns = new AtomicLong();
    private final AtomicLong guardBreakRuns = new AtomicLong();
    private final AtomicLong errorRuns = new AtomicLong();
    private final AtomicLong fallbackRuns = new AtomicLong();
    private final AtomicLong totalElapsedMs = new AtomicLong();
    private final AtomicReference<String> lastExitReason = new AtomicReference<>();
    private final AtomicReference<String> lastGuardReason = new AtomicReference<>();
    private final AtomicReference<String> lastUpdatedAt = new AtomicReference<>();
    private final MeterRegistry meterRegistry;

    public AgentGraphRunMonitorImpl(MeterRegistry meterRegistry) {
        this.meterRegistry = meterRegistry;
    }

    @Override
    public void onRunFinished(AgentState state) {
        if (state == null) {
            return;
        }
        totalRuns.incrementAndGet();
        String exitReason = state.getString(AgentState.KEY_EXIT_REASON);
        String intent = state.getString(AgentState.KEY_INTENT);
        recordRunMetric(exitReason, intent);

        if (AgentState.EXIT_COMPLETE.equals(exitReason)) {
            completedRuns.incrementAndGet();
        } else if (AgentState.EXIT_PENDING_CONFIRMATION.equals(exitReason)) {
            pendingConfirmationRuns.incrementAndGet();
        } else if (AgentState.EXIT_GUARD_BREAK.equals(exitReason)) {
            guardBreakRuns.incrementAndGet();
        } else if (AgentState.EXIT_ERROR.equals(exitReason) || AgentState.EXIT_MAX_ITERATIONS.equals(exitReason)) {
            errorRuns.incrementAndGet();
        }
        if ("FALLBACK".equals(intent)) {
            fallbackRuns.incrementAndGet();
        }

        Integer elapsedMs = state.getInt(AgentState.KEY_GUARD_ELAPSED_MS);
        if (elapsedMs != null && elapsedMs > 0) {
            totalElapsedMs.addAndGet(elapsedMs);
            recordElapsedMetric(elapsedMs, exitReason);
        }
        lastExitReason.set(exitReason);
        lastGuardReason.set(state.getString(AgentState.KEY_GUARD_REASON));
        lastUpdatedAt.set(LocalDateTime.now().format(TIME_FORMATTER));
    }

    @Override
    public AgentGraphHealthResponse snapshot() {
        long total = totalRuns.get();
        AgentGraphHealthResponse response = new AgentGraphHealthResponse();
        response.setTotalRuns(total);
        response.setCompletedRuns(completedRuns.get());
        response.setPendingConfirmationRuns(pendingConfirmationRuns.get());
        response.setGuardBreakRuns(guardBreakRuns.get());
        response.setErrorRuns(errorRuns.get());
        response.setFallbackRuns(fallbackRuns.get());
        response.setTotalElapsedMs(totalElapsedMs.get());
        response.setAverageElapsedMs(total == 0 ? 0 : totalElapsedMs.get() / total);
        response.setGuardBreakRate(total == 0 ? 0.0 : guardBreakRuns.get() * 1.0 / total);
        response.setFallbackRate(total == 0 ? 0.0 : fallbackRuns.get() * 1.0 / total);
        applyHealthStatus(response);
        response.setLastExitReason(lastExitReason.get());
        response.setLastGuardReason(lastGuardReason.get());
        response.setLastUpdatedAt(lastUpdatedAt.get());
        return response;
    }

    private void recordRunMetric(String exitReason, String intent) {
        Counter.builder("agent.graph.runs")
                .description("StateGraph agent run count")
                .tag("exit_reason", normalize(exitReason))
                .tag("intent", normalize(intent))
                .register(meterRegistry)
                .increment();
    }

    private void recordElapsedMetric(int elapsedMs, String exitReason) {
        Timer.builder("agent.graph.run.elapsed")
                .description("StateGraph agent run elapsed time")
                .tag("exit_reason", normalize(exitReason))
                .register(meterRegistry)
                .record(Duration.ofMillis(elapsedMs));
    }

    private void applyHealthStatus(AgentGraphHealthResponse response) {
        double guardRate = response.getGuardBreakRate();
        double fallbackRate = response.getFallbackRate();
        if (response.getTotalRuns() == 0) {
            response.setHealthStatus("UNKNOWN");
            response.setHealthMessage("暂无智能体运行数据");
        } else if (guardRate >= 0.2 || fallbackRate >= 0.3) {
            response.setHealthStatus("CRITICAL");
            response.setHealthMessage("智能体守卫中断或兜底比例偏高，需要排查路由、节点或外部模型可用性");
        } else if (guardRate >= 0.05 || fallbackRate >= 0.1) {
            response.setHealthStatus("WARN");
            response.setHealthMessage("智能体运行存在少量异常，建议关注 checkpoint 轨迹和最近守卫原因");
        } else {
            response.setHealthStatus("HEALTHY");
            response.setHealthMessage("智能体运行稳定");
        }
    }

    private String normalize(String value) {
        return value == null || value.isBlank() ? "UNKNOWN" : value;
    }
}
