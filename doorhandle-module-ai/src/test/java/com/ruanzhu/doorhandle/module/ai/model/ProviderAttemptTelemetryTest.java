package com.ruanzhu.doorhandle.module.ai.model;

import com.ruanzhu.doorhandle.framework.observability.RedactingSpanExporter;
import com.ruanzhu.doorhandle.module.ai.config.AgentModelProperties;
import io.agentscope.core.message.TextBlock;
import io.agentscope.core.model.*;
import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.common.AttributeKey;
import io.opentelemetry.sdk.OpenTelemetrySdk;
import io.opentelemetry.sdk.common.CompletableResultCode;
import io.opentelemetry.sdk.trace.SdkTracerProvider;
import io.opentelemetry.sdk.trace.data.SpanData;
import io.opentelemetry.sdk.trace.export.*;
import org.junit.jupiter.api.Test;
import reactor.core.publisher.Flux;
import java.time.Duration;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class ProviderAttemptTelemetryTest {
    @Test void fallbackReportsBothActualModelsAndNeverExportsTheProviderErrorBody(){
        var spans=new ArrayList<SpanData>();
        SpanExporter collector=new SpanExporter(){
            public CompletableResultCode export(Collection<SpanData> batch){spans.addAll(batch);return CompletableResultCode.ofSuccess();}
            public CompletableResultCode flush(){return CompletableResultCode.ofSuccess();}
            public CompletableResultCode shutdown(){return CompletableResultCode.ofSuccess();}
        };
        GlobalOpenTelemetry.resetForTest();
        try(var provider=SdkTracerProvider.builder().addSpanProcessor(SimpleSpanProcessor.create(new RedactingSpanExporter(collector,"fixture"))).build()){
            GlobalOpenTelemetry.set(OpenTelemetrySdk.builder().setTracerProvider(provider).build());
            var first=mock(Model.class);var second=mock(Model.class);
            when(first.getModelName()).thenReturn("actual-first");when(second.getModelName()).thenReturn("actual-backup");
            when(first.stream(anyList(),anyList(),any())).thenReturn(Flux.error(new java.io.IOException("private-upstream-response")));
            when(second.stream(anyList(),anyList(),any())).thenReturn(Flux.just(ChatResponse.builder().content(List.of(TextBlock.builder().text("private reply").build())).build()));
            var a=new ModelCircuit(2,Duration.ofSeconds(60),Duration.ofMinutes(5));var b=new ModelCircuit(2,Duration.ofSeconds(60),Duration.ofMinutes(5));
            new ManagedAgentModel(List.of(new ManagedAgentModel.Candidate("logical-a","openai",first,a),new ManagedAgentModel.Candidate("logical-b","dashscope",second,b)),null,new AgentModelProperties(),true)
                    .stream(List.of(),List.of(),null).blockLast(Duration.ofSeconds(5));
            assertThat(spans).hasSize(2);
            assertThat(spans.stream().map(s->s.getAttributes().get(AttributeKey.stringKey("gen_ai.request.model")))).containsExactly("actual-first","actual-backup");
            assertThat(spans).allSatisfy(span->{assertThat(span.getAttributes().get(AttributeKey.stringKey("doorhandle.observation.kind"))).isEqualTo("provider_attempt");assertThat(span.getStatus().getDescription()).isEmpty();assertThat(span.getEvents()).isEmpty();assertThat(span.getAttributes().toString()).doesNotContain("private");});
            verify(first,times(1)).stream(anyList(),anyList(),any());verify(second,times(1)).stream(anyList(),anyList(),any());
        }finally{GlobalOpenTelemetry.resetForTest();}
    }
}
