package com.ruanzhu.doorhandle.module.ai.model;

import org.junit.jupiter.api.Test;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicLong;
import static com.ruanzhu.doorhandle.module.ai.model.ModelFailureClassifier.Failure.*;
import static org.assertj.core.api.Assertions.*;

class ModelCircuitTest {
    private final AtomicLong time = new AtomicLong();
    private ModelCircuit circuit() { return new ModelCircuit(2, Duration.ofSeconds(60), Duration.ofMinutes(5), time::get); }

    @Test void transientFailuresOpenAtThresholdAndSuccessResetsConsecutiveFailures() {
        var circuit = circuit();
        circuit.failure(circuit.acquire(), TRANSIENT);
        assertThat(circuit.health().state()).isEqualTo("CLOSED");
        circuit.success(circuit.acquire());
        circuit.failure(circuit.acquire(), TRANSIENT);
        assertThat(circuit.acquire()).isNotNull();
        circuit.failure(circuit.acquire(), TRANSIENT);
        assertThat(circuit.acquire()).isNull();
        assertThat(circuit.health().retryAfterSeconds()).isEqualTo(60);
    }
    @Test void quotaAndAuthenticationOpenImmediatelyWithLongerCooldown() {
        for (var failure : new ModelFailureClassifier.Failure[]{QUOTA, AUTH}) {
            var circuit = circuit(); circuit.failure(circuit.acquire(), failure);
            assertThat(circuit.acquire()).isNull(); assertThat(circuit.health().retryAfterSeconds()).isEqualTo(300);
        }
    }
    @Test void cooldownAdmitsOnlyOneProbeAndSuccessRestoresPrimary() {
        var circuit = circuit(); circuit.failure(circuit.acquire(), QUOTA);
        time.addAndGet(Duration.ofMinutes(5).toNanos());
        assertThat(circuit.health().state()).isEqualTo("PROBE_READY");
        var probe = circuit.acquire(); assertThat(probe.probe()).isTrue();
        for (int i = 0; i < 20; i++) assertThat(circuit.acquire()).isNull();
        assertThat(circuit.health().state()).isEqualTo("HALF_OPEN");
        circuit.success(probe);
        assertThat(circuit.health().state()).isEqualTo("CLOSED"); assertThat(circuit.acquire().probe()).isFalse();
    }
    @Test void failedProbeReopensAndCancellationReleasesProbe() {
        var circuit = circuit(); circuit.failure(circuit.acquire(), QUOTA);
        time.addAndGet(Duration.ofMinutes(5).toNanos());
        var cancelled = circuit.acquire(); circuit.release(cancelled);
        var next = circuit.acquire(); assertThat(next).isNotNull();
        circuit.release(cancelled);
        assertThat(circuit.acquire()).isNull(); // 旧取消的再次清理不释放新探测。
        circuit.failure(next, TRANSIENT);
        assertThat(circuit.health().state()).isEqualTo("OPEN"); assertThat(circuit.health().retryAfterSeconds()).isEqualTo(60);
    }
    @Test void staleConcurrentCompletionCannotCloseAnOpenedCircuit() {
        var circuit = circuit(); var old = circuit.acquire();
        circuit.failure(circuit.acquire(), QUOTA);
        circuit.success(old); circuit.release(old); circuit.failure(old, TRANSIENT);
        assertThat(circuit.health().lastFailure()).isEqualTo("QUOTA"); assertThat(circuit.acquire()).isNull();
    }
}
