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
