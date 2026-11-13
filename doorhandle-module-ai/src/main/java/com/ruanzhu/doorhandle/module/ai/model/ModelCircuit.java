package com.ruanzhu.doorhandle.module.ai.model;

import java.time.Duration;
import java.util.function.LongSupplier;
import java.util.concurrent.TimeUnit;
import io.github.resilience4j.circuitbreaker.CircuitBreaker;
import io.github.resilience4j.circuitbreaker.CircuitBreakerConfig;

/** 进程内共享健康状态；冷却结束后只允许一个真实请求探测，不额外调用付费模型。 */
class ModelCircuit {
    private final int threshold;
    private final Duration cooldown;
    private final Duration quotaCooldown;
    private final LongSupplier nanoTime;
    private final CircuitBreaker breaker;
    private long generation;
    private long openedAt;
    private long waitNanos;
    private boolean open;
    private boolean probing;
    private ModelFailureClassifier.Failure lastFailure;

    ModelCircuit(int threshold, Duration cooldown, Duration quotaCooldown) {
        this(threshold, cooldown, quotaCooldown, System::nanoTime);
    }
    ModelCircuit(int threshold, Duration cooldown, Duration quotaCooldown, LongSupplier nanoTime) {
        if(threshold<1||cooldown.isNegative()||quotaCooldown.isNegative())throw new IllegalArgumentException("模型熔断参数无效");
        this.threshold = threshold; this.cooldown = cooldown; this.quotaCooldown = quotaCooldown; this.nanoTime = nanoTime;
        // 成功即重置窗口，保持既有“连续失败”契约。计时、代次和取消票据仍由门面负责；
        // 不启后台探针，不装饰整个 Agent，也不重试付费结果未知的调用。
        breaker=CircuitBreaker.of("model-local",CircuitBreakerConfig.custom().slidingWindowSize(threshold)
                .minimumNumberOfCalls(threshold).failureRateThreshold(100)
                .permittedNumberOfCallsInHalfOpenState(1).automaticTransitionFromOpenToHalfOpenEnabled(false)
                .waitDurationInOpenState(Duration.ofDays(3650)).writableStackTraceEnabled(false).build());
    }
    record Permit(long generation, boolean probe, String token) {
        Permit(long generation,boolean probe){this(generation,probe,"");}
    }
    record Health(String state, String lastFailure, long retryAfterSeconds) {}

    synchronized Permit acquire() {
        if (!open) return breaker.tryAcquirePermission()?new Permit(generation, false):null;
        if (remaining() > 0 || probing) return null;
        generation++; // 每个探测有独立票据，旧探测的清理不能释放新探测。
        if(breaker.getState()!=CircuitBreaker.State.HALF_OPEN)breaker.transitionToHalfOpenState();
        if(!breaker.tryAcquirePermission())return null;
        probing = true;
        return new Permit(generation, true);
    }
    synchronized void success(Permit permit) {
        if (permit.generation() != generation) return;
        breaker.onSuccess(0,TimeUnit.NANOSECONDS);breaker.reset();
        open = false; probing = false; lastFailure = null;
        if (permit.probe()) generation++;
    }
    synchronized void failure(Permit permit, ModelFailureClassifier.Failure reason) {
        if (permit.generation() != generation) return;
        lastFailure = reason;
        breaker.onError(0,TimeUnit.NANOSECONDS,new ModelAttemptFailure(reason));
        if (permit.probe() || breaker.getState()==CircuitBreaker.State.OPEN || reason == ModelFailureClassifier.Failure.QUOTA
                || reason == ModelFailureClassifier.Failure.AUTH) {
            if(breaker.getState()!=CircuitBreaker.State.OPEN)breaker.transitionToOpenState();
            open = true; probing = false; openedAt = nanoTime.getAsLong();
            waitNanos = (reason == ModelFailureClassifier.Failure.QUOTA || reason == ModelFailureClassifier.Failure.AUTH
                    ? quotaCooldown : cooldown).toNanos();
            generation++;
        }
    }
    synchronized void release(Permit permit) {
        if (permit.generation() == generation && permit.probe()) {probing = false;breaker.releasePermission();}
    }
    synchronized Health health() {
        String state = !open ? "CLOSED" : probing ? "HALF_OPEN" : remaining() > 0 ? "OPEN" : "PROBE_READY";
        return new Health(state, lastFailure == null ? null : lastFailure.name(),
                open ? (remaining() + 999_999_999L) / 1_000_000_000L : 0);
    }
    private long remaining() { return Math.max(0, waitNanos - (nanoTime.getAsLong() - openedAt)); }
    String engine(){return "resilience4j";}
    private static final class ModelAttemptFailure extends RuntimeException {
        ModelAttemptFailure(ModelFailureClassifier.Failure reason){super(reason.name(),null,false,false);}
    }
}
