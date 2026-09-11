package com.ruanzhu.doorhandle.module.app.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.app.config.properties.DeepSeekProperties;
import com.ruanzhu.doorhandle.module.system.security.SensitiveDataSanitizer;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class DeepSeekClientStreamingTest {

    private HttpServer server;

    @BeforeEach
    void setUp() throws IOException {
        server = HttpServer.create(new InetSocketAddress(0), 0);
        server.createContext("/v1/chat/completions", this::handle);
        server.start();
    }

    @AfterEach
    void tearDown() {
        if (server != null) {
            server.stop(0);
        }
    }

    @Test
    void generateOpsResponseStreamEmitsTokensAndReturnsCompleteContent() {
        DeepSeekClient client = newClient();
        List<String> tokens = new ArrayList<>();

        String content = client.generateOpsResponseStream("系统状态", "OSS 已配置", tokens::add);

        assertThat(tokens).containsExactly("系统", "正常");
        assertThat(content).isEqualTo("系统正常");
    }

    @Test
    void rewriteRagQueryUsesShortRagTimeoutAndFallsBackToOriginalPrompt() {
        DeepSeekClient client = newClient(150);

        long startedAt = System.currentTimeMillis();
        String rewritten = client.rewriteRagQuery("质检队列怎么处理返工");
        long elapsedMs = System.currentTimeMillis() - startedAt;

        assertThat(rewritten).isEqualTo("质检队列怎么处理返工");
        assertThat(elapsedMs).isLessThan(1000);
    }

    private DeepSeekClient newClient() {
        return newClient(1000);
    }

    private DeepSeekClient newClient(int ragReadTimeoutMs) {
        DeepSeekProperties properties = new DeepSeekProperties();
        properties.setEnabled(true);
        properties.setApiKey("test-key");
        properties.setBaseUrl("http://localhost:" + server.getAddress().getPort());
        properties.setConnectTimeoutMs(1000);
        properties.setReadTimeoutMs(3000);
        properties.setRagReadTimeoutMs(ragReadTimeoutMs);
        return new DeepSeekClient(properties, new ObjectMapper(), new SensitiveDataSanitizer());
    }

    private void handle(HttpExchange exchange) throws IOException {
        String requestBody = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        if (!requestBody.contains("\"stream\":true")) {
            try {
                Thread.sleep(600);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
            respond(exchange, 200, "{\"choices\":[{\"message\":{\"content\":\"慢查询改写\"}}]}");
            return;
        }
        String body = """
                data: {"choices":[{"delta":{"content":"系统"}}]}

                data: {"choices":[{"delta":{"content":"正常"}}]}

                data: [DONE]

                """;
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "text/event-stream");
        exchange.sendResponseHeaders(200, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }

    private void respond(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }
}
