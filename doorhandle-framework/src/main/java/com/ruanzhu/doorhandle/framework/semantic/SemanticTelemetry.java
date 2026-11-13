package com.ruanzhu.doorhandle.framework.semantic;

import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.trace.SpanKind;
import io.opentelemetry.api.trace.StatusCode;
import java.util.function.Supplier;

final class SemanticTelemetry {
    private SemanticTelemetry() { }
    static <T> T call(String operation,String purpose,String model,Supplier<T> work) {
        var span=GlobalOpenTelemetry.getTracer("doorhandle.semantic").spanBuilder(operation).setSpanKind(SpanKind.CLIENT)
                .setAttribute("doorhandle.index.kind",purpose).setAttribute("gen_ai.request.model",model)
                .setAttribute("db.system.name",operation.startsWith("vector.")?"qdrant":"embedding-bridge").startSpan();
        try(var scope=span.makeCurrent()){return work.get();}
        catch(RuntimeException failure){span.setStatus(StatusCode.ERROR,"semantic_operation_failed");throw failure;}
        finally{span.end();}
    }
}
