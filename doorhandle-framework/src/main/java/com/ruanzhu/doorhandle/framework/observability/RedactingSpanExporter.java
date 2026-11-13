package com.ruanzhu.doorhandle.framework.observability;

import io.opentelemetry.api.common.AttributeKey;
import io.opentelemetry.api.common.AttributeType;
import io.opentelemetry.api.common.Attributes;
import io.opentelemetry.sdk.common.CompletableResultCode;
import io.opentelemetry.sdk.resources.Resource;
import io.opentelemetry.sdk.trace.data.*;
import io.opentelemetry.sdk.trace.export.SpanExporter;
import java.util.Collection;
import java.util.List;
import java.util.Set;

/** 出站白名单：不发送提示词、工具正文、异常 message/stack、URL、身份或 baggage。 */
public final class RedactingSpanExporter implements SpanExporter {
    private static final Set<String> TEXT=Set.of("gen_ai.operation.name","gen_ai.agent.name","gen_ai.request.model",
            "gen_ai.tool.name","doorhandle.run.id","doorhandle.model.config_version","doorhandle.tool.policy_version",
            "doorhandle.sop.version","doorhandle.role","langfuse.trace.name","langfuse.trace.metadata.run_id",
            "db.system.name","doorhandle.index.kind","gen_ai.provider.name","doorhandle.model.id","doorhandle.observation.kind");
    private final SpanExporter delegate;
    private final String serviceName;
    public RedactingSpanExporter(SpanExporter delegate,String serviceName){this.delegate=delegate;this.serviceName=serviceName;}
    public static Attributes sanitize(Attributes source){
        var result=Attributes.builder();
        source.forEach((key,value)->{
            String name=key.getKey();
            if(key.getType()==AttributeType.STRING&&TEXT.contains(name)&&value instanceof String text
                    &&text.matches("[A-Za-z0-9_:.,/ -]{1,128}")&&!text.contains("://"))
                result.put(AttributeKey.stringKey(name),text);
            else if(key.getType()==AttributeType.LONG&&(name.startsWith("gen_ai.usage.")
                    ||name.equals("agentscope.usage.tool_use_prompt_tokens")||name.equals("gen_ai.request.messages.count")
                    ||name.equals("gen_ai.request.tools.count")||name.equals("gen_ai.tool.call.count"))&&value instanceof Long number&&number>=0)
                result.put(AttributeKey.longKey(name),number);
        });return result.build();
    }
    public SpanData redact(SpanData original){
        return new SafeSpanSnapshot(original,serviceName);
    }
    @Override public CompletableResultCode export(Collection<SpanData> spans){return delegate.export(spans.stream().map(this::redact).toList());}
    @Override public CompletableResultCode flush(){return delegate.flush();}
    @Override public CompletableResultCode shutdown(){return delegate.shutdown();}
}
