package com.ruanzhu.doorhandle.module.ai.model;

import io.agentscope.core.model.ChatUsage;
import io.micrometer.core.instrument.Metrics;
import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.StatusCode;
import java.util.Set;
import java.util.concurrent.atomic.AtomicBoolean;

/** 每个实际供应商尝试单独成 span，备用模型不冒充主模型；不参与额度/审计的正确性路径。 */
final class ProviderAttemptTelemetry {
    private final Span span;
    private final String provider;
    private final AtomicBoolean ended=new AtomicBoolean();
    private ProviderAttemptTelemetry(Span span,String provider){this.span=span;this.provider=provider;}
    static ProviderAttemptTelemetry start(String id,String provider,io.agentscope.core.model.Model model){
        String safe=provider!=null&&Set.of("openai","dashscope","deepseek").contains(provider)?provider:"other";
        try {
            return new ProviderAttemptTelemetry(GlobalOpenTelemetry.getTracer("doorhandle.model")
                    .spanBuilder("provider.attempt").setAttribute("gen_ai.operation.name","chat")
                    .setAttribute("gen_ai.request.model",model.getModelName()).setAttribute("gen_ai.provider.name",safe)
                    .setAttribute("doorhandle.model.id",id).setAttribute("doorhandle.observation.kind","provider_attempt").startSpan(),safe);
        }catch(RuntimeException ignored){return new ProviderAttemptTelemetry(Span.getInvalid(),safe);}
    }
    void complete(ChatUsage usage){finish("success",usage);}
    void failed(){finish("error",null);}
    void cancelled(){finish("cancelled",null);}
    private void finish(String outcome,ChatUsage usage){
        if(!ended.compareAndSet(false,true))return;
        try {
            if(usage!=null){span.setAttribute("gen_ai.usage.input_tokens",(long)usage.getInputTokens());span.setAttribute("gen_ai.usage.output_tokens",(long)usage.getOutputTokens());}
            span.setStatus("success".equals(outcome)?StatusCode.OK:StatusCode.ERROR);span.end();
            Metrics.counter("doorhandle.model.attempts","provider",provider,"outcome",outcome).increment();
        }catch(RuntimeException ignored){/* 观测失败不能改变模型结果、审计或扣额。 */}
    }
}
