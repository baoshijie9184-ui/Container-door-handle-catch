package com.ruanzhu.doorhandle.module.ai.agent;

import com.ruanzhu.doorhandle.framework.observability.RedactingSpanExporter;
import com.ruanzhu.doorhandle.framework.observability.TelemetryContext;
import io.agentscope.core.ReActAgent;
import io.agentscope.core.message.TextBlock;
import io.agentscope.core.model.ChatResponse;
import io.agentscope.core.model.Model;
import io.agentscope.core.tool.Toolkit;
import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.common.AttributeKey;
import io.opentelemetry.sdk.OpenTelemetrySdk;
import io.opentelemetry.sdk.common.CompletableResultCode;
import io.opentelemetry.sdk.trace.SdkTracerProvider;
import io.opentelemetry.sdk.trace.data.SpanData;
import io.opentelemetry.sdk.trace.export.SimpleSpanProcessor;
import io.opentelemetry.sdk.trace.export.SpanExporter;
import org.junit.jupiter.api.Test;
import reactor.core.publisher.Flux;
import java.time.Duration;
import java.util.Collection;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class AgentTelemetryMiddlewareTest {
    @Test void nativeAgentAndModelSpansShareRunAndVersionsWithoutConversationBody(){
        var spans=new CopyOnWriteArrayList<SpanData>();
        SpanExporter collector=new SpanExporter(){
            public CompletableResultCode export(Collection<SpanData> batch){spans.addAll(batch);return CompletableResultCode.ofSuccess();}
            public CompletableResultCode flush(){return CompletableResultCode.ofSuccess();}
            public CompletableResultCode shutdown(){return CompletableResultCode.ofSuccess();}
        };
        GlobalOpenTelemetry.resetForTest();
        try(var provider=SdkTracerProvider.builder().addSpanProcessor(TelemetryContext.processor())
                .addSpanProcessor(SimpleSpanProcessor.create(new RedactingSpanExporter(collector,"agent-fixture"))).build()){
            GlobalOpenTelemetry.set(OpenTelemetrySdk.builder().setTracerProvider(provider).build());
            var model=mock(Model.class);when(model.getModelName()).thenReturn("fixture-model");
            when(model.stream(anyList(),anyList(),any())).thenReturn(Flux.just(ChatResponse.builder()
                    .content(List.of(TextBlock.builder().text("private answer").build())).build()));
            try(var agent=ReActAgent.builder().name("fixture-agent").model(model).toolkit(new Toolkit())
                    .middleware(new AgentTelemetryMiddleware("fixture-agent","INSPECTOR","opaque-run","fixture-model",17,"skill-a:3"))
                    .enableMetaTool(false).enableTaskList(false).build()){
                agent.call("private question and credential").block(Duration.ofSeconds(5));
            }
            assertThat(spans).hasSizeGreaterThanOrEqualTo(2);
            assertThat(spans).allSatisfy(span->{
                assertThat(span.getAttributes().get(AttributeKey.stringKey("doorhandle.run.id"))).isEqualTo("opaque-run");
                assertThat(span.getAttributes().get(AttributeKey.stringKey("doorhandle.model.config_version"))).isEqualTo("17");
                assertThat(span.getAttributes().get(AttributeKey.stringKey("doorhandle.sop.version"))).isEqualTo("skill-a:3");
                assertThat(span.getEvents()).isEmpty();assertThat(span.getAttributes().toString()).doesNotContain("private");
            });
            assertThat(spans.stream().map(SpanData::getTraceId).distinct()).hasSize(1);
            assertThat(spans.stream().map(SpanData::getName)).contains("invoke_agent","chat");
        }finally{GlobalOpenTelemetry.resetForTest();}
    }
}
