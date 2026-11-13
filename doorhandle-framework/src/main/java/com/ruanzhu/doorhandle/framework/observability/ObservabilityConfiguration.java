package com.ruanzhu.doorhandle.framework.observability;

import io.micrometer.core.instrument.MeterRegistry;
import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.common.AttributeKey;
import io.opentelemetry.api.common.Attributes;
import io.opentelemetry.context.propagation.ContextPropagators;
import io.opentelemetry.api.trace.propagation.W3CTraceContextPropagator;
import io.opentelemetry.exporter.otlp.http.trace.OtlpHttpSpanExporter;
import io.opentelemetry.sdk.OpenTelemetrySdk;
import io.opentelemetry.sdk.resources.Resource;
import io.opentelemetry.sdk.trace.*;
import io.opentelemetry.sdk.trace.samplers.Sampler;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Base64;

@Configuration(proxyBeanMethods=false)
@EnableConfigurationProperties(ObservabilityProperties.class)
public class ObservabilityConfiguration {
    @Bean(destroyMethod="close")
    public SdkTracerProvider doorhandleTracerProvider(ObservabilityProperties properties,MeterRegistry meters){
        var builder=SdkTracerProvider.builder().setResource(Resource.create(Attributes.of(AttributeKey.stringKey("service.name"),properties.getServiceName())))
                .setSpanLimits(SpanLimits.builder().setMaxNumberOfAttributes(48).setMaxAttributeValueLength(128)
                        .setMaxNumberOfEvents(0).setMaxNumberOfLinks(0).build())
                .setSampler(properties.isTracingEnabled()?Sampler.traceIdRatioBased(properties.getSampleRatio()):Sampler.alwaysOff())
                .addSpanProcessor(TelemetryContext.processor());
        if(properties.isTracingEnabled()){
            validate(properties);
            // SDK 的原始响应、URL 和异常不进应用日志；固定失败计数仍由包装导出器提供。
            java.util.logging.Logger.getLogger("io.opentelemetry.exporter").setLevel(java.util.logging.Level.OFF);
            java.util.logging.Logger.getLogger("io.opentelemetry.sdk.trace.export").setLevel(java.util.logging.Level.OFF);
            String pair=TelemetrySecrets.read(properties.getPublicKeyFile())+":"+TelemetrySecrets.read(properties.getSecretKeyFile());
            var exporter=OtlpHttpSpanExporter.builder().setEndpoint(properties.getEndpoint())
                    .addHeader("Authorization","Basic "+Base64.getEncoder().encodeToString(pair.getBytes(StandardCharsets.UTF_8)))
                    .addHeader("x-langfuse-ingestion-version","4").setTimeout(Duration.ofMillis(properties.getTimeoutMillis())).build();
            builder.addSpanProcessor(new BoundedTelemetryProcessor(new RedactingSpanExporter(exporter,properties.getServiceName()),properties,meters));
        }
        return builder.build();
    }
    @Bean(destroyMethod="")
    public OpenTelemetrySdk doorhandleOpenTelemetry(SdkTracerProvider provider,ObservabilityProperties properties){
        var sdk=OpenTelemetrySdk.builder().setTracerProvider(provider)
                .setPropagators(ContextPropagators.create(W3CTraceContextPropagator.getInstance())).build();
        // 同一 SDK 供 Micrometer 和 AgentScope 使用，禁止并行 javaagent/global SDK。
        if(properties.isTracingEnabled())GlobalOpenTelemetry.set(sdk);return sdk;
    }
    static void validate(ObservabilityProperties p){
        try {
            URI uri=URI.create(p.getEndpoint());
            if(!java.util.Set.of("http","https").contains(uri.getScheme())||uri.getHost()==null||uri.getUserInfo()!=null
                    ||uri.getQuery()!=null||uri.getFragment()!=null||!uri.getPath().equals("/api/public/otel/v1/traces")
                    ||p.getQueueSize()<16||p.getQueueSize()>16384||p.getBatchSize()<1||p.getBatchSize()>p.getQueueSize()
                    ||p.getTimeoutMillis()<100||p.getTimeoutMillis()>10000||!Double.isFinite(p.getSampleRatio())
                    ||p.getSampleRatio()<0||p.getSampleRatio()>1||!p.getServiceName().matches("[A-Za-z0-9_.-]{1,64}"))throw new IllegalArgumentException();
        }catch(RuntimeException ignored){throw new IllegalStateException("TELEMETRY_CONFIG_INVALID");}
    }
}
