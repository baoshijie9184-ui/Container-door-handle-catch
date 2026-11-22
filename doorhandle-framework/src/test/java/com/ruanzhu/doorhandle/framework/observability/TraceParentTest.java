package com.ruanzhu.doorhandle.framework.observability;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import io.opentelemetry.api.baggage.Baggage;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanContext;
import io.opentelemetry.api.trace.TraceFlags;
import io.opentelemetry.api.trace.TraceState;
import io.opentelemetry.context.Context;
import java.time.Duration;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.*;

class TraceParentTest {
    @Test
    void preservesOnlyTheW3cParentAcrossDispatch() {
        var span = SpanContext.create("0123456789abcdef0123456789abcdef", "0123456789abcdef",
                TraceFlags.getSampled(), TraceState.builder().put("vendor", "private").build());
        var source = Context.root().with(Span.wrap(span))
                .with(Baggage.builder().put("identity", "private").build());
        var redis = mock(StringRedisTemplate.class);
        @SuppressWarnings("unchecked")
        ValueOperations<String, String> values = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(values);
        var props = new ObservabilityProperties();
        props.setTracingEnabled(true);
        var lifetime = Duration.ofMinutes(30);
        var store = new TraceContextStore(redis, props, new SimpleMeterRegistry());
        String header = "00-" + span.getTraceId() + "-" + span.getSpanId() + "-01";
        try (var scope = source.makeCurrent()) {
            store.remember("inbox:request", lifetime);
        }
        String key = "doorhandle:telemetry:parent:inbox:request";
        verify(values).set(key, header, lifetime);
        when(values.get(key)).thenReturn(header);
        var restored = store.restore("inbox:request");
        var parent = Span.fromContext(restored).getSpanContext();
        assertThat(parent.getTraceId()).isEqualTo(span.getTraceId());
        assertThat(parent.getSpanId()).isEqualTo(span.getSpanId());
        assertThat(parent.isSampled()).isTrue();
        assertThat(parent.getTraceState().isEmpty()).isTrue();
        assertThat(Baggage.fromContext(restored).isEmpty()).isTrue();
    }

    @Test
    void missingOrUnavailableContextAllowsAnIndependentTrace() {
        var redis = mock(StringRedisTemplate.class);
        var props = new ObservabilityProperties();
        props.setTracingEnabled(true);
        var meters = new SimpleMeterRegistry();
        var store = new TraceContextStore(redis, props, meters);
        when(redis.opsForValue()).thenThrow(new DataAccessResourceFailureException("offline"));
        assertThat(Span.fromContext(store.restore("inbox:request")).getSpanContext().isValid()).isFalse();
        assertThat(meters.get("doorhandle.telemetry.correlation.failures").tag("operation", "read").counter().count())
                .isEqualTo(1);
        assertThat(Span.fromContext(TraceParent.restore("invalid")).getSpanContext().isValid()).isFalse();
    }
}
