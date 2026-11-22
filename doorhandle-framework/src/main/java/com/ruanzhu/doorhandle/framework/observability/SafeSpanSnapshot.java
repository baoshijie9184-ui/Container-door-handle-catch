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
    private static final AttributeKey<String> OPERATION=AttributeKey.stringKey("gen_ai.operation.name");
    private static final AttributeKey<String> OBSERVATION_KIND=AttributeKey.stringKey("doorhandle.observation.kind");
    private static final AttributeKey<String> OBSERVATION_TYPE=AttributeKey.stringKey("langfuse.observation.type");
    private static final AttributeKey<String> DATABASE_SYSTEM=AttributeKey.stringKey("db.system.name");
    private final String name;
    private final Attributes attributes;
    private final SpanContext context,parent;
    private final SpanKind kind;
    private final long start,end;
    private final StatusData status;
    private final Resource resource;
    SafeSpanSnapshot(SpanData raw,String service){
        var allowed=RedactingSpanExporter.sanitize(raw.getAttributes());
        String operation=allowed.get(OPERATION);
        boolean providerAttempt="chat".equals(operation)&&"provider_attempt".equals(allowed.get(OBSERVATION_KIND));
        var output=allowed.toBuilder();
        if(!providerAttempt)output.removeIf(key->modelOnly(key.getKey()));
        // AgentScope's chat wrapper and the physical provider span describe the same usage.
        // Derive the export type from known operations instead of letting the backend infer it from GenAI fields.
        output.put(OBSERVATION_TYPE,observationType(allowed,providerAttempt));
        attributes=output.build();
        name = raw.getKind() == SpanKind.SERVER ? "http.server.request"
                : operation == null ? "doorhandle.operation" : operation;
        context=withoutState(raw.getSpanContext());parent=withoutState(raw.getParentSpanContext());
        kind=raw.getKind();start=raw.getStartEpochNanos();end=raw.getEndEpochNanos();
        status=StatusData.create(raw.getStatus().getStatusCode(),"");
        resource=Resource.create(Attributes.of(AttributeKey.stringKey("service.name"),service));
    }
    private static boolean modelOnly(String key){
        return key.equals("gen_ai.request.model")||key.equals("gen_ai.provider.name")
                ||key.startsWith("gen_ai.usage.")||key.equals("agentscope.usage.tool_use_prompt_tokens");
    }
    private static String observationType(Attributes allowed,boolean providerAttempt){
        if(providerAttempt)return "generation";
        return switch(java.util.Objects.toString(allowed.get(OPERATION),"")){
            case "invoke_agent"->"agent";
            case "execute_tool"->"tool";
            default->"embedding-bridge".equals(allowed.get(DATABASE_SYSTEM))?"embedding":"span";
        };
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
