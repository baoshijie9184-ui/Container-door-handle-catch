package com.ruanzhu.doorhandle.framework.semantic;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.IntStream;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

/** The mock HTTP server, like every test in this repository, runs on ECS only. */
class MemoryBridgeEmbeddingClientTest {
    @Test void acceptsProtectedDense1024ResponsesAndBatchesUnicodeInputsEightEightOne() throws Exception {
        var json = new ObjectMapper();
        var calls = new AtomicInteger();
        var embedded = new AtomicInteger();
        List<JsonNode> requests = new CopyOnWriteArrayList<>();
        List<String> tokens = new CopyOnWriteArrayList<>();
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/internal/embeddings", exchange -> {
            calls.incrementAndGet();
            var request = json.readTree(exchange.getRequestBody());
            requests.add(request);
            tokens.add(exchange.getRequestHeaders().getFirst("x-doorhandle-memory-token"));
            var vectors = new ArrayList<List<Float>>();
            for (JsonNode ignored : request.path("texts")) vectors.add(dense(embedded.getAndIncrement()));
            byte[] body = json.writeValueAsBytes(success(request, vectors));
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
        try {
            var client = new MemoryBridgeEmbeddingClient(new SemanticProperties(), json,
                "http://127.0.0.1:" + server.getAddress().getPort(), "fixture-private-token");
            List<String> texts = IntStream.range(0, 17)
                .mapToObj(i -> "知识片段-" + i + "：鹈鹕🚲\n第二行 保留原文").toList();
            var actual = client.embed(texts, new EmbeddingClient.RequestContext("SYSTEM_RAG", "doorhandlecatch:system"));
            assertThat(calls.get()).isEqualTo(3);
            assertThat(requests).extracting(node -> node.path("texts").size()).containsExactly(8, 8, 1);
            assertThat(tokens).containsExactly("fixture-private-token", "fixture-private-token", "fixture-private-token");
            var transmitted = new ArrayList<String>();
            var requestIds = new ArrayList<String>();
            for (JsonNode request : requests) {
                assertThat(request.path("app_id").asText()).isEqualTo("doorhandlecatch");
                assertThat(request.path("purpose").asText()).isEqualTo("SYSTEM_RAG");
                assertThat(request.path("user_id").asText()).isEqualTo("doorhandlecatch:system");
                String id = request.path("request_id").asText();
                assertThat(UUID.fromString(id).toString()).isEqualTo(id);
                requestIds.add(id);
                request.path("texts").forEach(node -> transmitted.add(node.asText()));
            }
            assertThat(requestIds).doesNotHaveDuplicates();
            assertThat(transmitted).containsExactlyElementsOf(texts);
            assertThat(actual).hasSize(17);
            for (int i = 0; i < actual.size(); i++) {
                assertThat(actual.get(i)).hasSize(1024).containsExactlyElementsOf(dense(i));
                assertThat(actual.get(i)).allSatisfy(value -> assertThat(value).isFinite().isNotZero());
            }
        } finally { server.stop(0); }
    }

    @Test void stopsAfterFailedSecondBatchWithoutRetryOrReturningPartialVectors() throws Exception {
        var json = new ObjectMapper();
        var calls = new AtomicInteger();
        List<Integer> sizes = new CopyOnWriteArrayList<>();
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/internal/embeddings", exchange -> {
            int call = calls.incrementAndGet();
            var request = json.readTree(exchange.getRequestBody());
            sizes.add(request.path("texts").size());
            byte[] body = call == 1 ? json.writeValueAsBytes(success(request,
                IntStream.range(0, 8).mapToObj(MemoryBridgeEmbeddingClientTest::dense).toList()))
                : "{}".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(call == 1 ? 200 : 503, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
        try {
            var client = new MemoryBridgeEmbeddingClient(new SemanticProperties(), json,
                "http://127.0.0.1:" + server.getAddress().getPort(), "fixture-private-token");
            var texts = IntStream.range(0, 17).mapToObj(i -> "synthetic-" + i).toList();
            assertThatThrownBy(() -> client.embed(texts,
                new EmbeddingClient.RequestContext("KNOWLEDGE", "doorhandlecatch:user:42")))
                .isInstanceOf(SemanticUnavailableException.class).hasMessage("EMBEDDING_BRIDGE_UNAVAILABLE");
            assertThat(calls.get()).isEqualTo(2);
            assertThat(sizes).containsExactly(8, 8);
        } finally { server.stop(0); }
    }

    private static List<Float> dense(int input) {
        return IntStream.range(0, 1024).mapToObj(dimension -> (input + 1) / 32f + dimension / 4096f).toList();
    }

    private static Map<String, Object> success(JsonNode request, List<List<Float>> vectors) {
        return Map.of("schemaVersion", 1, "request_id", request.path("request_id").asText(),
            "profile", "siliconflow-bge-m3-v1", "provider", "siliconflow", "model", "BAAI/bge-m3",
            "dimensions", 1024, "preprocessing", "utf8-newline-space-v1", "input_count", vectors.size(), "vectors", vectors);
    }

    @Test void sharesPrivateBridgeAndRejectsWrongIdentityWithoutRetryOrPaidFallback() throws Exception {
        var calls=new AtomicInteger();var json=new ObjectMapper();var server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/internal/embeddings",exchange->{
            calls.incrementAndGet();var request=json.readTree(exchange.getRequestBody());
            assertThat(exchange.getRequestHeaders().getFirst("x-doorhandle-memory-token")).isEqualTo("fixture-private-token");
            byte[] body=json.writeValueAsBytes(Map.of("schemaVersion",1,"request_id",request.path("request_id").asText(),"profile","foreign-profile","provider","siliconflow","model","BAAI/bge-m3","dimensions",1024,"preprocessing","utf8-newline-space-v1","input_count",1,"vectors",List.of(List.of(1))));
            exchange.sendResponseHeaders(200,body.length);exchange.getResponseBody().write(body);exchange.close();
        });server.start();
        try {
            var client=new MemoryBridgeEmbeddingClient(new SemanticProperties(),json,"http://127.0.0.1:"+server.getAddress().getPort(),"fixture-private-token");
            var context=new EmbeddingClient.RequestContext("KNOWLEDGE","doorhandlecatch:user:42");
            assertThatThrownBy(()->client.embed(List.of("source"),context)).isInstanceOf(SemanticUnavailableException.class).hasMessage("EMBEDDING_IDENTITY_MISMATCH");
            assertThat(calls.get()).isEqualTo(1);
            assertThatThrownBy(()->client.embed(List.of("好".repeat(2667)),context)).isInstanceOf(IllegalArgumentException.class);
            assertThat(calls.get()).isEqualTo(1);
        } finally {server.stop(0);}
    }
}
