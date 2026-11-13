package com.ruanzhu.doorhandle.framework.observability;

import com.sun.net.httpserver.HttpServer;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import io.opentelemetry.api.trace.StatusCode;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Base64;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import static org.assertj.core.api.Assertions.*;

/** 只在ECS测试环境启动私有假接收端，不调用模型或外部摄入服务。 */
class OtlpHttpContractTest {
    @TempDir Path temporary;
    @Test void pinnedSdkSendsProtobufBasicAndV4ToExactPathWithoutSensitiveBody()throws Exception{
        String publicKey="pk-lf-fixture-public-key-1234",secretKey="sk-lf-fixture-secret-key-1234";
        Path pub=temporary.resolve("public"),secret=temporary.resolve("secret");
        Files.writeString(pub,publicKey);Files.writeString(secret,secretKey);
        var auth=new AtomicReference<String>();var version=new AtomicReference<String>();
        var contentType=new AtomicReference<String>();var body=new AtomicReference<byte[]>();
        HttpServer receiver=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        receiver.createContext("/api/public/otel/v1/traces",exchange->{
            auth.set(exchange.getRequestHeaders().getFirst("Authorization"));
            version.set(exchange.getRequestHeaders().getFirst("x-langfuse-ingestion-version"));
            contentType.set(exchange.getRequestHeaders().getFirst("Content-Type"));
            body.set(exchange.getRequestBody().readNBytes(65536));
            exchange.getResponseHeaders().set("Content-Type","application/x-protobuf");
            exchange.sendResponseHeaders(200,-1);exchange.close();
        });
        receiver.start();
        var meters=new SimpleMeterRegistry();
        try{
            var p=new ObservabilityProperties();p.setTracingEnabled(true);p.setSampleRatio(1);p.setBatchSize(1);
            p.setPublicKeyFile(pub.toString());p.setSecretKeyFile(secret.toString());
            p.setEndpoint("http://127.0.0.1:"+receiver.getAddress().getPort()+"/api/public/otel/v1/traces");
            try(var provider=new ObservabilityConfiguration().doorhandleTracerProvider(p,meters)){
                var span=provider.get("fixture").spanBuilder("private prompt").startSpan();
                span.setAttribute("gen_ai.operation.name","chat").setAttribute("gen_ai.request.model","fixture-model")
                        .setAttribute("user.id","private-user").setAttribute("gen_ai.input.messages","private-password")
                        .setStatus(StatusCode.ERROR,"private-exception").recordException(new IllegalStateException("private-exception"));
                span.end();provider.forceFlush().join(5,TimeUnit.SECONDS);
            }
            assertThat(auth.get()).isEqualTo("Basic "+Base64.getEncoder().encodeToString((publicKey+":"+secretKey).getBytes(StandardCharsets.UTF_8)));
            assertThat(version.get()).isEqualTo("4");assertThat(contentType.get()).startsWith("application/x-protobuf");
            assertThat(body.get()).isNotEmpty();
            assertThat(new String(body.get(),StandardCharsets.ISO_8859_1)).contains("fixture-model").doesNotContain("private-","private prompt");
        }finally{try{meters.close();}finally{receiver.stop(0);}}
    }
}
