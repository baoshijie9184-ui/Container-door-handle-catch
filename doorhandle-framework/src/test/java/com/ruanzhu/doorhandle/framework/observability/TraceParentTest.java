package com.ruanzhu.doorhandle.framework.observability;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowPayloads.ConversationInputV1;
import io.opentelemetry.api.baggage.Baggage;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanContext;
import io.opentelemetry.api.trace.TraceFlags;
import io.opentelemetry.api.trace.TraceState;
import io.opentelemetry.context.Context;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class TraceParentTest {
    @Test
    void preservesOnlyTheW3cParentAcrossStoredQueueChanges() throws Exception {
        var span = SpanContext.create("0123456789abcdef0123456789abcdef", "0123456789abcdef",
                TraceFlags.getSampled(), TraceState.builder().put("vendor", "private").build());
        var source = Context.root().with(Span.wrap(span))
                .with(Baggage.builder().put("identity", "private").build());
        String header;
        try (var scope = source.makeCurrent()) {
            header = TraceParent.capture();
        }
        var input = new ConversationInputV1("inspector", "NEXT_TURN", "NEXT_TURN",
                "CHAT", "read", "0".repeat(64), null, header);
        var json = new ObjectMapper();
        var stored = json.readValue(json.writeValueAsBytes(input.withQueueOrder(3).withContent("", "0".repeat(64))),
                ConversationInputV1.class);
        var restored = TraceParent.restore(stored.traceparent());
        var parent = Span.fromContext(restored).getSpanContext();
        assertThat(parent.getTraceId()).isEqualTo(span.getTraceId());
        assertThat(parent.getSpanId()).isEqualTo(span.getSpanId());
        assertThat(parent.isSampled()).isTrue();
        assertThat(parent.getTraceState().isEmpty()).isTrue();
        assertThat(Baggage.fromContext(restored).isEmpty()).isTrue();
    }

    @Test
    void oldOrMalformedParentDoesNotCreateAnInvalidTrace() throws Exception {
        var json = new ObjectMapper();
        var old = new ConversationInputV1("inspector", "NEXT_TURN", "NEXT_TURN",
                "CHAT", "read", "0".repeat(64));
        assertThat(json.writeValueAsString(old)).doesNotContain("traceparent");
        assertThat(Span.fromContext(TraceParent.restore(null)).getSpanContext().isValid()).isFalse();
        assertThat(Span.fromContext(TraceParent.restore("invalid")).getSpanContext().isValid()).isFalse();
    }
}
