package com.ruanzhu.doorhandle.module.ai.model;

import java.time.Duration;
import java.util.function.LongSupplier;

/** 进程内共享健康状态；冷却结束后只允许一个真实请求探测，不额外调用付费模型。 */
class ModelCircuit {
    private final int threshold;
    private final Duration cooldown;
    private final Duration quotaCooldown;
    private final LongSupplier nanoTime;
    private int failures;
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
        this.threshold = threshold; this.cooldown = cooldown; this.quotaCooldown = quotaCooldown; this.nanoTime = nanoTime;
    }
    record Permit(long generation, boolean probe, String token) {
        Permit(long generation,boolean probe){this(generation,probe,"");}
    }
    record Health(String state, String lastFailure, long retryAfterSeconds) {}

    synchronized Permit acquire() {
        if (!open) return new Permit(generation, false);
        if (remaining() > 0 || probing) return null;
        generation++; // 每个探测有独立票据，旧探测的清理不能释放新探测。
        probing = true;
        return new Permit(generation, true);
    }
    synchronized void success(Permit permit) {
        if (permit.generation() != generation) return;
        failures = 0; open = false; probing = false; lastFailure = null;
        if (permit.probe()) generation++;
    }
    synchronized void failure(Permit permit, ModelFailureClassifier.Failure reason) {
        if (permit.generation() != generation) return;
        lastFailure = reason;
        if (permit.probe() || ++failures >= threshold || reason == ModelFailureClassifier.Failure.QUOTA
                || reason == ModelFailureClassifier.Failure.AUTH) {
            open = true; probing = false; openedAt = nanoTime.getAsLong();
            waitNanos = (reason == ModelFailureClassifier.Failure.QUOTA || reason == ModelFailureClassifier.Failure.AUTH
                    ? quotaCooldown : cooldown).toNanos();
            generation++;
        }
    }
    synchronized void release(Permit permit) {
        if (permit.generation() == generation && permit.probe()) probing = false;
    }
    synchronized Health health() {
        String state = !open ? "CLOSED" : probing ? "HALF_OPEN" : remaining() > 0 ? "OPEN" : "PROBE_READY";
        return new Health(state, lastFailure == null ? null : lastFailure.name(),
                open ? (remaining() + 999_999_999L) / 1_000_000_000L : 0);
    }
    private long remaining() { return Math.max(0, waitNanos - (nanoTime.getAsLong() - openedAt)); }
}
