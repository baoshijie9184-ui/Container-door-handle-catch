package com.ruanzhu.doorhandle.framework.observability;

import io.opentelemetry.api.common.Attributes;
import io.opentelemetry.context.ContextKey;
import io.opentelemetry.context.Context;
import io.opentelemetry.sdk.trace.ReadWriteSpan;
import io.opentelemetry.sdk.trace.ReadableSpan;
import io.opentelemetry.sdk.trace.SpanProcessor;

/** 只传播已授权的运行/版本元数据，不接收外部 baggage 或用户文本。 */
public final class TelemetryContext {
    public static final ContextKey<Attributes> ATTRIBUTES=ContextKey.named("doorhandle.telemetry.attributes");
    private TelemetryContext(){}
    public static SpanProcessor processor(){return new SpanProcessor(){
        public void onStart(Context parent,ReadWriteSpan span){var data=parent.get(ATTRIBUTES);if(data!=null)RedactingSpanExporter.sanitize(data).forEach((key,value)->putAbsent(span,key,value));}
        public boolean isStartRequired(){return true;}
        public void onEnd(ReadableSpan span){}
        public boolean isEndRequired(){return false;}
    };}
    @SuppressWarnings({"rawtypes","unchecked"})
    private static void putAbsent(ReadWriteSpan span,io.opentelemetry.api.common.AttributeKey key,Object value){if(span.getAttribute(key)==null)span.setAttribute(key,value);}
}
