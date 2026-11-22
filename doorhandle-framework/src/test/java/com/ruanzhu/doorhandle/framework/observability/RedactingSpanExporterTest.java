package com.ruanzhu.doorhandle.framework.observability;

import io.opentelemetry.api.common.AttributeKey;
import io.opentelemetry.api.common.Attributes;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.sdk.trace.data.*;
import io.opentelemetry.sdk.trace.export.SpanExporter;
import io.opentelemetry.sdk.resources.Resource;
import org.junit.jupiter.api.Test;
import java.util.List;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class RedactingSpanExporterTest {
    @Test void whitelistDropsPayloadIdentityUrlsAndWrongTypes(){
        var safe=RedactingSpanExporter.sanitize(Attributes.builder().put("gen_ai.operation.name","chat")
                .put("gen_ai.request.model","BGE-M3").put("gen_ai.usage.input_tokens",123L)
                .put("doorhandle.run.id","opaque-run-1").put("user.id","alice")
                .put("gen_ai.input.messages","password=SECRET").put("exception.message","SECRET")
                .put("gen_ai.request.model","https://private/?key=SECRET").put("gen_ai.usage.output_tokens",-1L).build());
        assertThat(safe.asMap()).containsEntry(AttributeKey.stringKey("gen_ai.operation.name"),"chat")
                .containsEntry(AttributeKey.longKey("gen_ai.usage.input_tokens"),123L)
                .doesNotContainKeys(AttributeKey.stringKey("user.id"),AttributeKey.stringKey("gen_ai.input.messages"),
                        AttributeKey.stringKey("exception.message"),AttributeKey.stringKey("gen_ai.request.model"),AttributeKey.longKey("gen_ai.usage.output_tokens"));
    }
    @Test void exporterRemovesExceptionEventsLinksStatusResourceAndDynamicName(){
        SpanData raw=mock(SpanData.class);
        when(raw.getAttributes()).thenReturn(Attributes.of(AttributeKey.stringKey("gen_ai.operation.name"),"chat"));
        when(raw.getStatus()).thenReturn(StatusData.create(StatusCode.ERROR,"private provider response"));
        when(raw.getName()).thenReturn("private question");
        when(raw.getResource()).thenReturn(Resource.create(Attributes.of(AttributeKey.stringKey("process.command_line"),"password")));
        var safe=new RedactingSpanExporter(mock(SpanExporter.class),"doorhandle-test").redact(raw);
        assertThat(safe.getName()).isEqualTo("chat");assertThat(safe.getEvents()).isEmpty();assertThat(safe.getLinks()).isEmpty();
        assertThat(safe.getStatus().getStatusCode()).isEqualTo(StatusCode.ERROR);assertThat(safe.getStatus().getDescription()).isEmpty();
        assertThat(safe.getResource().getAttributes().asMap()).hasSize(1).containsEntry(AttributeKey.stringKey("service.name"),"doorhandle-test");
    }
    @Test void supplierAttemptsOwnUsageWhileOtherSpansKeepTheirLifecycleType(){
        var exporter=new RedactingSpanExporter(mock(SpanExporter.class),"doorhandle-test");
        var model=AttributeKey.stringKey("gen_ai.request.model");
        var outputTokens=AttributeKey.longKey("gen_ai.usage.output_tokens");
        var observationType=AttributeKey.stringKey("langfuse.observation.type");
        var route=AttributeKey.stringKey("doorhandle.model.route");
        var chat=Attributes.builder().put("gen_ai.operation.name","chat")
                .put(model,"physical-model").put(outputTokens,42L).put(route,"selected-route");
        var wrapper=exporter.redact(raw(chat.put(observationType,"generation").build()));
        assertThat(wrapper.getAttributes().asMap()).containsEntry(observationType,"span")
                .containsEntry(route,"selected-route").doesNotContainKeys(model,outputTokens);
        var attempt=exporter.redact(raw(chat.put("doorhandle.observation.kind","provider_attempt").build()));
        assertThat(attempt.getAttributes().asMap()).containsEntry(observationType,"generation")
                .containsEntry(model,"physical-model").containsEntry(outputTokens,42L);
        assertThat(exporter.redact(attempt).getAttributes()).isEqualTo(attempt.getAttributes());
        var tool=exporter.redact(raw(chat.put("gen_ai.operation.name","execute_tool").build()));
        assertThat(tool.getAttributes().asMap()).containsEntry(observationType,"tool").doesNotContainKeys(model,outputTokens);
        var embeddingModel=AttributeKey.stringKey("doorhandle.embedding.model");
        var embedding=exporter.redact(raw(Attributes.builder().put("db.system.name","embedding-bridge")
                .put(embeddingModel,"BGE-M3").build()));
        assertThat(embedding.getAttributes().asMap()).containsEntry(observationType,"embedding")
                .containsEntry(embeddingModel,"BGE-M3").doesNotContainKeys(model,outputTokens);
    }
    private static SpanData raw(Attributes attributes){
        SpanData span=mock(SpanData.class);
        when(span.getAttributes()).thenReturn(attributes);
        when(span.getStatus()).thenReturn(StatusData.unset());
        return span;
    }
    @Test void acceptsOnlyLangfuseHttpTraceEndpointAndBoundedSettings(){
        var p=new ObservabilityProperties();p.setEndpoint("http://langfuse:3000/api/public/otel/v1/traces");
        assertThatCode(()->ObservabilityConfiguration.validate(p)).doesNotThrowAnyException();
        for(String invalid:List.of("http://localhost:4317","http://u:p@langfuse/api/public/otel/v1/traces","http://langfuse/api/public/otel/v1/traces?secret=x")){
            p.setEndpoint(invalid);assertThatThrownBy(()->ObservabilityConfiguration.validate(p)).hasMessage("TELEMETRY_CONFIG_INVALID");
        }
        p.setEndpoint("https://langfuse.example/api/public/otel/v1/traces");p.setQueueSize(100000);
        assertThatThrownBy(()->ObservabilityConfiguration.validate(p)).hasMessage("TELEMETRY_CONFIG_INVALID");
    }
}
