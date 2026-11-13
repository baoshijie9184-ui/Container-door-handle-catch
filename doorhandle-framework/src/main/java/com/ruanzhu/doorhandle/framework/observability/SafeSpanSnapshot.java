package com.ruanzhu.doorhandle.framework.observability;

import io.opentelemetry.api.common.AttributeKey;
import io.opentelemetry.api.common.Attributes;
import io.opentelemetry.api.trace.SpanContext;
import io.opentelemetry.api.trace.SpanKind;
import io.opentelemetry.api.trace.TraceState;
import io.opentelemetry.sdk.common.InstrumentationLibraryInfo;
import io.opentelemetry.sdk.common.InstrumentationScopeInfo;
import io.opentelemetry.sdk.resources.Resource;
import io.opentelemetry.sdk.trace.ReadableSpan;
import io.opentelemetry.sdk.trace.data.*;
import java.util.List;

/** 队列只持有安全值，不通过 delegate 间接保留原 span、异常正文或身份属性。 */
final class SafeSpanSnapshot implements SpanData,ReadableSpan {
    private final String name;
    private final Attributes attributes;
    private final SpanContext context,parent;
    private final SpanKind kind;
    private final long start,end;
    private final StatusData status;
    private final Resource resource;
    SafeSpanSnapshot(SpanData raw,String service){
        attributes=RedactingSpanExporter.sanitize(raw.getAttributes());
        String operation=attributes.get(AttributeKey.stringKey("gen_ai.operation.name"));
        name=operation==null?"doorhandle.operation":operation;
        context=withoutState(raw.getSpanContext());parent=withoutState(raw.getParentSpanContext());
        kind=raw.getKind();start=raw.getStartEpochNanos();end=raw.getEndEpochNanos();
        status=StatusData.create(raw.getStatus().getStatusCode(),"");
        resource=Resource.create(Attributes.of(AttributeKey.stringKey("service.name"),service));
    }
    private static SpanContext withoutState(SpanContext value){
        if(value==null||!value.isValid())return SpanContext.getInvalid();
        return value.isRemote()?SpanContext.createFromRemoteParent(value.getTraceId(),value.getSpanId(),value.getTraceFlags(),TraceState.getDefault())
                :SpanContext.create(value.getTraceId(),value.getSpanId(),value.getTraceFlags(),TraceState.getDefault());
    }
    @Override public String getName(){return name;}
    @Override public SpanKind getKind(){return kind;}
    @Override public SpanContext getSpanContext(){return context;}
    @Override public SpanContext getParentSpanContext(){return parent;}
    @Override public StatusData getStatus(){return status;}
    @Override public long getStartEpochNanos(){return start;}
    @Override public long getEndEpochNanos(){return end;}
    @Override public Attributes getAttributes(){return attributes;}
    @Override public List<EventData> getEvents(){return List.of();}
    @Override public List<LinkData> getLinks(){return List.of();}
    @Override public boolean hasEnded(){return true;}
    @Override public int getTotalRecordedEvents(){return 0;}
    @Override public int getTotalRecordedLinks(){return 0;}
    @Override public int getTotalAttributeCount(){return attributes.size();}
    @Override public Resource getResource(){return resource;}
    @Override public InstrumentationLibraryInfo getInstrumentationLibraryInfo(){return InstrumentationLibraryInfo.create("doorhandle.redacted",null);}
    @Override public InstrumentationScopeInfo getInstrumentationScopeInfo(){return InstrumentationScopeInfo.create("doorhandle.redacted");}
    @Override public SpanData toSpanData(){return this;}
    @Override public long getLatencyNanos(){return Math.max(0,end-start);}
    @Override public <T> T getAttribute(AttributeKey<T> key){return attributes.get(key);}
}
