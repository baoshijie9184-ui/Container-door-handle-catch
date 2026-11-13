package com.ruanzhu.doorhandle.framework.observability;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.opentelemetry.context.Context;
import io.opentelemetry.sdk.common.CompletableResultCode;
import io.opentelemetry.sdk.trace.*;
import io.opentelemetry.sdk.trace.data.SpanData;
import io.opentelemetry.sdk.trace.export.*;
import java.time.Duration;
import java.util.Collection;
import java.util.concurrent.Semaphore;

/** BatchSpanProcessor 负责后台导出；信号线程只 tryAcquire，队满丢遥测而不阻塞业务。 */
final class BoundedTelemetryProcessor implements SpanProcessor {
    private final Semaphore slots;
    private final Counter dropped;
    private final Counter rejected;
    private final String serviceName;
    private final BatchSpanProcessor batch;
    BoundedTelemetryProcessor(SpanExporter exporter,ObservabilityProperties config,MeterRegistry meters){
        slots=new Semaphore(config.getQueueSize());
        serviceName=config.getServiceName();
        dropped=meters.counter("doorhandle.telemetry.spans.dropped","reason","queue_full");
        rejected=meters.counter("doorhandle.telemetry.spans.dropped","reason","sanitization_failed");
        Counter failures=meters.counter("doorhandle.telemetry.export.failures");
        SpanExporter releasing=new SpanExporter(){
            public CompletableResultCode export(Collection<SpanData> spans){
                int count=spans.size();
                try {
                    CompletableResultCode result=exporter.export(spans);
                    return result.whenComplete(()->{slots.release(count);if(!result.isSuccess())failures.increment();});
                }catch(RuntimeException ignored){slots.release(count);failures.increment();return CompletableResultCode.ofFailure();}
            }
            public CompletableResultCode flush(){return exporter.flush();}
            public CompletableResultCode shutdown(){return exporter.shutdown();}
        };
        batch=BatchSpanProcessor.builder(releasing).setMaxQueueSize(config.getQueueSize())
                .setMaxExportBatchSize(config.getBatchSize()).setScheduleDelay(Duration.ofSeconds(1))
                .setExporterTimeout(Duration.ofMillis(config.getTimeoutMillis())).build();
    }
    @Override public void onStart(Context parent,ReadWriteSpan span){}
    @Override public boolean isStartRequired(){return false;}
    @Override public void onEnd(ReadableSpan span){
        if(!span.getSpanContext().isSampled())return;
        if(!slots.tryAcquire()){dropped.increment();return;}
        try{batch.onEnd(new SafeSpanSnapshot(span.toSpanData(),serviceName));}
        catch(RuntimeException ignored){slots.release();rejected.increment();}
    }
    @Override public boolean isEndRequired(){return true;}
    @Override public CompletableResultCode shutdown(){return batch.shutdown();}
    @Override public CompletableResultCode forceFlush(){return batch.forceFlush();}
}
