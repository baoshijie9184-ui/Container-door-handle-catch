package com.ruanzhu.doorhandle.framework.observability;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import io.opentelemetry.api.common.Attributes;
import io.opentelemetry.sdk.common.CompletableResultCode;
import io.opentelemetry.sdk.trace.SdkTracerProvider;
import io.opentelemetry.sdk.trace.data.SpanData;
import io.opentelemetry.sdk.trace.export.SpanExporter;
import org.junit.jupiter.api.Test;
import java.util.Collection;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import static org.assertj.core.api.Assertions.*;

class BoundedTelemetryProcessorTest {
    @Test void exporterOutageNeverFailsBusinessAndQueueDropsAreCounted()throws Exception{
        var started=new CountDownLatch(1);var pending=new CompletableResultCode();
        SpanExporter exporter=new SpanExporter(){
            public CompletableResultCode export(Collection<SpanData> spans){started.countDown();return pending;}
            public CompletableResultCode flush(){return CompletableResultCode.ofSuccess();}
            public CompletableResultCode shutdown(){pending.fail();return CompletableResultCode.ofSuccess();}
        };
        var settings=new ObservabilityProperties();settings.setQueueSize(16);settings.setBatchSize(1);settings.setTimeoutMillis(100);
        var meters=new SimpleMeterRegistry();
        try(var provider=SdkTracerProvider.builder().addSpanProcessor(new BoundedTelemetryProcessor(exporter,settings,meters)).build()){
            var tracer=provider.get("bounded-test");tracer.spanBuilder("first").startSpan().end();
            assertThat(started.await(2,TimeUnit.SECONDS)).isTrue();
            for(int i=0;i<100;i++)tracer.spanBuilder("business").startSpan().end();
            assertThat(meters.counter("doorhandle.telemetry.spans.dropped","reason","queue_full").count()).isPositive();
            pending.fail();provider.forceFlush().join(2,TimeUnit.SECONDS);
            assertThat(meters.counter("doorhandle.telemetry.export.failures").count()).isPositive();
        }finally{meters.close();}
    }
}
