package com.ruanzhu.doorhandle.module.ai.model;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.ai.config.AgentModelProperties;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import com.sun.net.httpserver.HttpServer;
import io.agentscope.core.ReActAgent;
import io.agentscope.core.message.TextBlock;
import io.agentscope.core.message.UserMessage;
import io.agentscope.core.model.GenerateOptions;
import io.agentscope.core.tool.*;
import org.junit.jupiter.api.*;
import reactor.core.publisher.Mono;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;

class AgentModelServiceTest {
    private final ObjectMapper json = new ObjectMapper();
    private final List<JsonNode> requests = new CopyOnWriteArrayList<>();
    private final List<String> credentials = new CopyOnWriteArrayList<>();
    private final List<String> headers = new CopyOnWriteArrayList<>();
    private HttpServer server;
    private AgentModelProperties connections;
    private AgentScopeProperties agent;

    @BeforeEach void start() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/responses", exchange -> {
            JsonNode request = json.readTree(exchange.getRequestBody());
            requests.add(request); credentials.add(exchange.getRequestHeaders().getFirst("Authorization"));
            headers.add(exchange.getRequestHeaders().getFirst("x-openai-actor-authorization"));
            boolean tools = request.has("tools") && !request.get("tools").isEmpty();
            boolean resultReceived = request.get("input").toString().contains("function_call_output");
            Map<String, Object> item = tools && !resultReceived
                    ? Map.of("id", "fc-1", "type", "function_call", "call_id", "call-1", "name", "lookup_task", "arguments", "{\"taskId\":\"t1\"}", "status", "completed")
                    : Map.of("id", "msg-1", "type", "message", "role", "assistant", "status", "completed", "content",
                            List.of(Map.of("type", "output_text", "text", "任务已读取", "annotations", List.of())));
            Map<String, Object> response = Map.of("id", "resp-test", "object", "response", "created_at", 1,
                    "model", "gpt-test", "status", "completed", "output", List.of(item));
            Map<String, Object> delta = tools && !resultReceived
                    ? Map.of("type", "response.function_call_arguments.delta", "item_id", "fc-1", "output_index", 0, "sequence_number", 1, "delta", "{\"taskId\":\"t1\"}")
                    : Map.of("type", "response.output_text.delta", "item_id", "msg-1", "output_index", 0, "content_index", 0, "sequence_number", 1, "delta", "任务已读取", "logprobs", List.of());
            String sse = "data: " + json.writeValueAsString(Map.of("type", "response.output_item.added", "sequence_number", 0, "output_index", 0, "item", item))
                    + "\n\ndata: " + json.writeValueAsString(delta)
                    + "\n\ndata: " + json.writeValueAsString(Map.of("type", "response.completed", "sequence_number", 2, "response", response)) + "\n\n";
            byte[] bytes = sse.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "text/event-stream");
            exchange.sendResponseHeaders(200, bytes.length); exchange.getResponseBody().write(bytes); exchange.close();
        });
        server.start();
        connections = new AgentModelProperties(); connections.setMaxRetries(0);
        connections.setTimeout(Duration.ofSeconds(5)); connections.setActorAuthorization("fixture-actor");
        connections.setFirstTokenTimeout(Duration.ofSeconds(2));
        connections.getOpenai().setApiKey("fixture-openai-secret");
        connections.getOpenai().setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort() + "/v1");
        connections.getOpenai().setModel("gpt-test");
        agent = new AgentScopeProperties(); agent.setModel("openai-official:gpt-test");
    }
    @AfterEach void stop() { server.stop(0); }

    @Test void responsesBindsCredentialsHeadersStorageAndToolsThroughSdk() throws Exception {
        var models = new AgentModelService(connections, agent);
        var calls = new AtomicInteger();
        var toolkit = new Toolkit();
        toolkit.registerAgentTool(new AgentTool() {
            public String getName() { return "lookup_task"; }
            public String getDescription() { return "读取授权任务"; }
            public boolean isReadOnly() { return true; }
            public Map<String, Object> getParameters() { return Map.of("type", "object", "properties", Map.of("taskId", Map.of("type", "string")), "required", List.of("taskId")); }
            public Mono<io.agentscope.core.message.ToolResultBlock> callAsync(ToolCallParam input) {
                assertThat(input.getInput().get("taskId")).isEqualTo("t1"); calls.incrementAndGet();
                return Mono.just(io.agentscope.core.message.ToolResultBlock.text("任务 t1 属于当前用户"));
            }
        });
        var runtime = ReActAgent.builder().name("test-agent").model(models.resolve(agent.getModel()))
                .toolkit(toolkit).enableMetaTool(false).enableTaskList(false).maxIters(3).build();
        var reply = runtime.call("读取任务").block(Duration.ofSeconds(15));
        assertThat(reply.getTextContent()).contains("任务已读取");
        assertThat(calls.get()).isEqualTo(1);
        assertThat(requests).hasSize(2);
        assertThat(credentials).containsOnly("Bearer fixture-openai-secret");
        assertThat(headers).containsOnly("fixture-actor");
        assertThat(requests).allSatisfy(request -> { assertThat(request.get("store").asBoolean()).isFalse(); assertThat(request.get("model").asText()).isEqualTo("gpt-test"); });
        assertThat(requests.get(1).get("input").toString()).contains("function_call_output", "call-1", "任务 t1");
        String catalog = json.writeValueAsString(models.catalog());
        assertThat(catalog).contains("RESPONSES", "deepseek", "dashscope").doesNotContain("fixture-openai-secret", "fixture-actor", "127.0.0.1");
    }

    @Test void onlyRegisteredModelsWithOwnCredentialsCanBeSelected() {
        var models = new AgentModelService(connections, agent);
        assertThatThrownBy(() -> models.resolve("openai-official:unregistered")).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> models.resolve("deepseek:deepseek-flash")).isInstanceOf(IllegalStateException.class);
        connections.getOpenai().setBaseUrl("https://user:secret@example.com/v1");
        assertThatThrownBy(() -> new AgentModelService(connections, agent).resolve(agent.getModel())).isInstanceOf(IllegalArgumentException.class);
    }

    @Test void chatProvidersUseSeparateCredentialsAndCorrectEndpoints() throws Exception {
        var authByModel = new java.util.concurrent.ConcurrentHashMap<String, String>();
        com.sun.net.httpserver.HttpHandler handler = exchange -> {
            JsonNode request = json.readTree(exchange.getRequestBody());
            String name = request.get("model").asText();
            authByModel.put(name, exchange.getRequestHeaders().getFirst("Authorization"));
            byte[] body = json.writeValueAsBytes(Map.of("id", "chat-1", "object", "chat.completion", "created", 1, "model", name,
                    "choices", List.of(Map.of("index", 0, "message", Map.of("role", "assistant", "content", "OK"), "finish_reason", "stop"))));
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length); exchange.getResponseBody().write(body); exchange.close();
        };
        server.createContext("/chat/completions", handler);
        server.createContext("/v1/chat/completions", handler);
        server.createContext("/compatible-mode/v1/chat/completions", handler);
        String base = "http://127.0.0.1:" + server.getAddress().getPort();
        connections.getDashscope().setBaseUrl(base + "/compatible-mode/v1");
        connections.getDashscope().setApiKey("dashscope-fixture-key");
        connections.getDeepseek().setBaseUrl(base);
        connections.getDeepseek().setApiKey("deepseek-fixture-key");
        var models = new AgentModelService(connections, agent);
        for (String id : List.of("dashscope:qwen-plus", "deepseek:deepseek-flash")) {
            var response = models.resolve(id).stream(List.of(new UserMessage("Hello")), List.of(), GenerateOptions.builder().stream(false).build())
                    .collectList().block(Duration.ofSeconds(10));
            assertThat(response).isNotEmpty();
            assertThat(response.get(0).getContent()).anyMatch(block -> block instanceof TextBlock text && text.getText().equals("OK"));
        }
        assertThat(authByModel).containsEntry("qwen-plus", "Bearer dashscope-fixture-key")
                .containsEntry("deepseek-flash", "Bearer deepseek-fixture-key");
    }

    @Test void sdkQuotaErrorsUseTwoBackupsWithoutSdkRetriesAndShareHealthAcrossRequests() throws Exception {
        var primaryCalls = new AtomicInteger(); var deepseekCalls = new AtomicInteger(); var dashscopeCalls = new AtomicInteger();
        server.removeContext("/v1/responses");
        server.createContext("/v1/responses", exchange -> {
            primaryCalls.incrementAndGet(); exchange.getRequestBody().readAllBytes();
            byte[] body = "{\"error\":{\"message\":\"fixture quota secret\",\"code\":\"insufficient_quota\",\"type\":\"insufficient_quota\"}}".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(429, body.length); exchange.getResponseBody().write(body); exchange.close();
        });
        server.createContext("/v1/chat/completions", exchange -> {
            deepseekCalls.incrementAndGet(); exchange.getRequestBody().readAllBytes();
            byte[] body = "{\"error\":{\"message\":\"Insufficient Balance\",\"code\":\"insufficient_balance\"}}".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(402, body.length); exchange.getResponseBody().write(body); exchange.close();
        });
        server.createContext("/compatible-mode/v1/chat/completions", exchange -> {
            dashscopeCalls.incrementAndGet(); exchange.getRequestBody().readAllBytes();
            byte[] body = json.writeValueAsBytes(Map.of("id", "chat-backup", "object", "chat.completion", "created", 1, "model", "qwen-plus",
                    "choices", List.of(Map.of("index", 0, "message", Map.of("role", "assistant", "content", "backup success"), "finish_reason", "stop"))));
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length); exchange.getResponseBody().write(body); exchange.close();
        });
        String base = "http://127.0.0.1:" + server.getAddress().getPort();
        connections.getDeepseek().setBaseUrl(base); connections.getDeepseek().setApiKey("deepseek-fixture");
        connections.getDashscope().setBaseUrl(base + "/compatible-mode/v1"); connections.getDashscope().setApiKey("dashscope-fixture");
        connections.setMaxRetries(3); connections.setFallbackEnabled(true);
        // 主模型和重复备用项自动去重。
        connections.setFallbackModels(List.of("deepseek:deepseek-flash", "dashscope:qwen-plus", agent.getModel(), "deepseek:deepseek-flash"));
        var models = new AgentModelService(connections, agent);
        for (int i = 0; i < 2; i++) {
            var reply = models.resolve(agent.getModel()).stream(List.of(new UserMessage("test")), List.of(), GenerateOptions.builder().stream(false).build())
                    .collectList().block(Duration.ofSeconds(10));
            assertThat(reply).isNotEmpty();
            assertThat(reply.get(0).getContent()).anyMatch(block -> block instanceof TextBlock text && text.getText().equals("backup success"));
        }
        assertThat(primaryCalls).hasValue(1); assertThat(deepseekCalls).hasValue(1); assertThat(dashscopeCalls).hasValue(2);
        assertThat(models.catalog().fallbackModels()).containsExactly("deepseek:deepseek-flash", "dashscope:qwen-plus");
        assertThat(models.catalog().models()).filteredOn(info -> !info.provider().equals("dashscope"))
                .allSatisfy(info -> { assertThat(info.healthState()).isEqualTo("OPEN"); assertThat(info.lastFailure()).isEqualTo("QUOTA"); });
        assertThat(json.writeValueAsString(models.catalog())).doesNotContain("fixture quota secret", "Insufficient Balance", "127.0.0.1");
    }

    @Test void responsesQuotaEventUnderHttp200CanSwitchToChatCompletionsStream() {
        server.removeContext("/v1/responses");
        server.createContext("/v1/responses", exchange -> {
            exchange.getRequestBody().readAllBytes();
            byte[] body = "data: {\"type\":\"error\",\"sequence_number\":0,\"code\":\"insufficient_quota\",\"message\":\"fixture secret\",\"param\":null}\n\n".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "text/event-stream");
            exchange.sendResponseHeaders(200, body.length); exchange.getResponseBody().write(body); exchange.close();
        });
        server.createContext("/v1/chat/completions", exchange -> {
            exchange.getRequestBody().readAllBytes();
            byte[] body = ("data: {\"id\":\"chat-1\",\"object\":\"chat.completion.chunk\",\"created\":1,\"model\":\"deepseek-flash\",\"choices\":[{\"index\":0,\"delta\":{\"role\":\"assistant\",\"content\":\"stream backup\"},\"finish_reason\":\"stop\"}]}\n\ndata: [DONE]\n\n").getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "text/event-stream");
            exchange.sendResponseHeaders(200, body.length); exchange.getResponseBody().write(body); exchange.close();
        });
        connections.getDeepseek().setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
        connections.getDeepseek().setApiKey("fixture-deepseek"); connections.setFallbackEnabled(true);
        var models = new AgentModelService(connections, agent);
        var chunks = models.resolve(agent.getModel()).stream(List.of(new UserMessage("test")), List.of(), null).collectList().block(Duration.ofSeconds(10));
        assertThat(chunks.stream().flatMap(chunk -> chunk.getContent().stream()).filter(block -> block instanceof TextBlock)
                .map(block -> ((TextBlock) block).getText()).collect(java.util.stream.Collectors.joining())).contains("stream backup");
        assertThat(models.catalog().models()).filteredOn(info -> info.selected()).singleElement()
                .satisfies(info -> assertThat(info.lastFailure()).isEqualTo("QUOTA"));
    }
}
