package com.ruanzhu.doorhandle.framework.observability;

import io.micrometer.core.instrument.MeterRegistry;
import io.opentelemetry.context.Context;
import java.time.Duration;
import org.springframework.dao.DataAccessException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

/** Short-lived correlation metadata for the inbox and workbench dispatchers. */
@Component
public class TraceContextStore {
    private static final String PREFIX = "doorhandle:telemetry:parent:";
    private final StringRedisTemplate redis;
    private final ObservabilityProperties properties;
    private final MeterRegistry meters;

    public TraceContextStore(StringRedisTemplate redis, ObservabilityProperties properties, MeterRegistry meters) {
        this.redis = redis;
        this.properties = properties;
        this.meters = meters;
    }

    public void remember(String id, Duration lifetime) {
        if (!properties.isTracingEnabled() || id == null) return;
        String parent = TraceParent.capture();
        if (parent == null) return;
        try {
            redis.opsForValue().set(PREFIX + id, parent, lifetime);
        } catch (DataAccessException unavailable) {
            meters.counter("doorhandle.telemetry.correlation.failures", "operation", "write").increment();
        }
    }

    public Context restore(String id) {
        if (!properties.isTracingEnabled() || id == null) return Context.root();
        try {
            return TraceParent.restore(redis.opsForValue().get(PREFIX + id));
        } catch (DataAccessException unavailable) {
            meters.counter("doorhandle.telemetry.correlation.failures", "operation", "read").increment();
            return Context.root();
        }
    }
}
