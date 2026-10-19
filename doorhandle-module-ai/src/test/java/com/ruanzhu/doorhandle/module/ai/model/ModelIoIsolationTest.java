package com.ruanzhu.doorhandle.module.ai.model;

import com.ruanzhu.doorhandle.module.ai.config.AgentModelProperties;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import com.sun.net.httpserver.HttpServer;
import io.agentscope.core.message.TextBlock;
import io.agentscope.core.message.UserMessage;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class ModelIoIsolationTest {
    @Test void healthyBackupFinishesWhilePrimaryStillWaitsForHttpHeaders() throws Exception {
        var release=new CountDownLatch(1);
        var primaryCalls=new AtomicInteger();var backupCalls=new AtomicInteger();
        var armed=new java.util.concurrent.atomic.AtomicBoolean();
        var server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        var executor=Executors.newFixedThreadPool(2);server.setExecutor(executor);
        server.createContext("/v1/responses",exchange->{
            try {
                primaryCalls.incrementAndGet();exchange.getRequestBody().readAllBytes();
                if(armed.get())release.await(20,TimeUnit.SECONDS);
                byte[] body="{\"error\":{\"code\":\"insufficient_quota\",\"message\":\"controlled quota\"}}".getBytes(StandardCharsets.UTF_8);
                exchange.getResponseHeaders().set("Content-Type","application/json");
                exchange.sendResponseHeaders(429,body.length);exchange.getResponseBody().write(body);
            } catch(InterruptedException interrupted){Thread.currentThread().interrupt();}
            catch(java.io.IOException disconnected) { /* A cancelled request may disconnect. */ }
            finally {exchange.close();}
        });
        server.createContext("/v1/chat/completions",exchange->{
            try {
                backupCalls.incrementAndGet();exchange.getRequestBody().readAllBytes();
                byte[] body=("data: {\"id\":\"backup\",\"object\":\"chat.completion.chunk\",\"model\":\"deepseek-flash\",\"choices\":[{\"index\":0,\"delta\":{\"content\":\"OK\"},\"finish_reason\":null}]}\n\ndata: [DONE]\n\n").getBytes(StandardCharsets.UTF_8);
                exchange.getResponseHeaders().set("Content-Type","text/event-stream");
                exchange.sendResponseHeaders(200,body.length);exchange.getResponseBody().write(body);
            } finally {exchange.close();}
        });
        server.start();
        var config=new AgentModelProperties();config.setMaxRetries(0);
        config.setTimeout(Duration.ofSeconds(30));config.setFirstTokenTimeout(Duration.ofSeconds(20));
        String base="http://127.0.0.1:"+server.getAddress().getPort()+"/v1";
        config.getOpenai().setBaseUrl(base);config.getOpenai().setApiKey("local-primary");
        config.getDeepseek().setBaseUrl(base);config.getDeepseek().setApiKey("local-backup");
        config.setFallbackEnabled(false);
        var agent=new AgentScopeProperties();agent.setModel("openai-official:"+config.getOpenai().getModel());
        var service=new AgentModelService(config,agent);
        try {
            // Warm real SDK codecs, so a cold JVM is not mistaken for network delay.
            assertThatThrownBy(()->service.resolve(agent.getModel()).stream(List.of(new UserMessage("warm")),List.of(),null)
                    .collectList().block(Duration.ofSeconds(25))).isInstanceOf(IllegalStateException.class);
            service.resolve("deepseek:deepseek-flash").stream(List.of(new UserMessage("warm")),List.of(),null)
                    .collectList().block(Duration.ofSeconds(25));
            primaryCalls.set(0);backupCalls.set(0);armed.set(true);
            config.setFallbackEnabled(true);config.setFallbackModels(List.of("deepseek:deepseek-flash"));
            config.setFirstTokenTimeout(Duration.ofMillis(500));
            var events=new java.util.concurrent.CopyOnWriteArrayList<Map<String,Object>>();
            var trace=new ModelAttemptTrace((type,fields)->{var event=new java.util.LinkedHashMap<>(fields);event.put("type",type);events.add(event);});
            var response=service.resolve(agent.getModel()).stream(List.of(new UserMessage("test")),List.of(),null)
                    .contextWrite(ctx->ctx.put(ModelAttemptTrace.CONTEXT_KEY,trace)).collectList().block(Duration.ofSeconds(5));
            assertThat(response.stream().flatMap(c->c.getContent().stream()).filter(TextBlock.class::isInstance)
                    .map(TextBlock.class::cast).map(TextBlock::getText)).containsExactly("OK");
            assertThat(primaryCalls).hasValue(1);assertThat(backupCalls).hasValue(1);
            assertThat(release.getCount()).isEqualTo(1);
            assertThat(events.stream().filter(e->e.get("type").equals("MODEL_ATTEMPT_STARTED"))).hasSize(2);
            assertThat(events.stream().filter(e->e.get("type").equals("MODEL_FALLBACK_SELECTED"))).hasSize(1);
            assertThat(events.stream().filter(e->e.get("type").equals("MODEL_ATTEMPT_COMPLETED"))).hasSize(1);
        } finally {
            release.countDown();service.close();server.stop(0);executor.shutdownNow();
        }
        service.close();
        assertThatThrownBy(()->service.resolve(agent.getModel())).isInstanceOf(IllegalStateException.class).hasMessage("模型服务已关闭");
    }
}
