package com.ruanzhu.doorhandle.framework.observability;

import io.opentelemetry.api.trace.propagation.W3CTraceContextPropagator;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.propagation.TextMapGetter;
import java.util.HashMap;
import java.util.Map;

/** Persist only the W3C parent identifier across a durable execution boundary. */
public final class TraceParent {
    private static final String HEADER = "traceparent";
    private static final W3CTraceContextPropagator PROPAGATOR = W3CTraceContextPropagator.getInstance();
    private static final TextMapGetter<Map<String, String>> GETTER = new TextMapGetter<>() {
        @Override public Iterable<String> keys(Map<String, String> carrier) { return carrier.keySet(); }
        @Override public String get(Map<String, String> carrier, String key) { return carrier.get(key); }
    };

    private TraceParent() {}

    public static String capture() {
        var carrier = new HashMap<String, String>();
        PROPAGATOR.inject(Context.current(), carrier, Map::put);
        return carrier.get(HEADER);
    }

    public static Context restore(String parent) {
        return parent == null ? Context.root() : PROPAGATOR.extract(Context.root(), Map.of(HEADER, parent), GETTER);
    }
}
