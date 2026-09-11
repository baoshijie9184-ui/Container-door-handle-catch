package com.ruanzhu.doorhandle.module.app.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;

class ChromaRagStoreServiceTest {

    private HttpServer server;
    private AtomicInteger queryAttempts;
    private AtomicInteger deleteRequests;

    @BeforeEach
    void setUp() throws IOException {
        queryAttempts = new AtomicInteger();
        deleteRequests = new AtomicInteger();
        server = HttpServer.create(new InetSocketAddress(0), 0);
        server.createContext("/", this::handle);
        server.start();
    }

    @AfterEach
    void tearDown() {
        if (server != null) {
            server.stop(0);
        }
    }

    @Test
    void queryRetriesChromaAfterTransientFailure() {
        ChromaRagStoreService service = newService();
        boolean indexed = service.indexDocuments(List.of(new ChromaRagStoreService.RagDocument(
                "doc-1",
                "classpath:rag/system-user-guide.md",
                "系统手册",
                "质检队列支持返工复检"
        )));

        assertThat(indexed).isTrue();
        assertThat(service.query("质检队列", 1)).isEmpty();

        List<ChromaRagStoreService.RagDocument> recovered = service.query("质检队列", 1);

        assertThat(recovered).hasSize(1);
        assertThat(recovered.get(0).content()).contains("质检队列");
        assertThat(queryAttempts.get()).isEqualTo(2);
    }

    @Test
    void indexingDeletesOldVectorsForCurrentSourcesBeforeUpsert() {
        ChromaRagStoreService service = newService();

        boolean indexed = service.indexDocuments(List.of(
                new ChromaRagStoreService.RagDocument("doc-1", "file:docs/system-user-guide.md", "用户手册", "检测工作台说明"),
                new ChromaRagStoreService.RagDocument("doc-2", "file:docs/system-user-guide.md", "用户手册", "质检队列说明")
        ));

        assertThat(indexed).isTrue();
        assertThat(deleteRequests.get()).isEqualTo(1);
    }

    private ChromaRagStoreService newService() {
        ChatAssistantProperties properties = new ChatAssistantProperties();
        properties.setChromaEnabled(true);
        properties.setChromaBaseUrl("http://localhost:" + server.getAddress().getPort());
        properties.setChromaEmbeddingDimension(32);
        properties.setChromaConnectTimeoutMs(1000);
        properties.setChromaReadTimeoutMs(1000);
        return new ChromaRagStoreService(properties, new LocalTextEmbeddingService(properties), new ObjectMapper());
    }

    private void handle(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        if (path.endsWith("/collections") && "POST".equals(exchange.getRequestMethod())) {
            respond(exchange, 200, "{\"id\":\"collection-1\"}");
            return;
        }
        if (path.endsWith("/collection-1/delete") && "POST".equals(exchange.getRequestMethod())) {
            deleteRequests.incrementAndGet();
            respond(exchange, 200, "{}");
            return;
        }
        if (path.endsWith("/collection-1/upsert") && "POST".equals(exchange.getRequestMethod())) {
            respond(exchange, 200, "{}");
            return;
        }
        if (path.endsWith("/collection-1/query") && "POST".equals(exchange.getRequestMethod())) {
            if (queryAttempts.incrementAndGet() == 1) {
                respond(exchange, 500, "{\"error\":\"temporary\"}");
            } else {
                respond(exchange, 200, """
                        {
                          "documents": [["质检队列支持返工复检"]],
                          "metadatas": [[{"source":"file:docs/system-user-guide.md","title":"用户手册"}]],
                          "distances": [[0.1]]
                        }
                        """);
            }
            return;
        }
        respond(exchange, 404, "{}");
    }

    private void respond(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }
}
