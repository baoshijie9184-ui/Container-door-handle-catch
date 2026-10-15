package com.ruanzhu.doorhandle.module.ai.model;

import com.ruanzhu.doorhandle.module.ai.config.AgentModelProperties;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import io.agentscope.core.model.*;
import io.agentscope.core.model.transport.ProxyConfig;
import io.agentscope.extensions.model.openai.OpenAIChatModel;
import io.agentscope.extensions.model.openaiofficial.OpenAIResponsesChatModel;
import java.net.URI;
import java.util.List;
import java.util.Map;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.time.Duration;
import java.util.concurrent.ConcurrentHashMap;

/** Explicit Spring credential binding; no JVM environment or shared registry mutation. */
public class AgentModelService {
    private final AgentModelProperties connections;
    private final AgentScopeProperties agent;
    private final Map<String, Model> models = new ConcurrentHashMap<>();
    private final Map<String, ModelCircuit> health = new ConcurrentHashMap<>();

    public AgentModelService(AgentModelProperties connections, AgentScopeProperties agent) {
        this.connections = connections;
        this.agent = agent;
        positive(connections.getTimeout()); positive(connections.getFirstTokenTimeout());
        positive(connections.getCircuitCooldown()); positive(connections.getQuotaCooldown());
        if (connections.getFirstTokenTimeout().compareTo(connections.getTimeout()) > 0)
            throw new IllegalArgumentException("首字超时不能超过模型总超时");
        if (connections.getFailureThreshold() < 1 || connections.getMaxRetries() < 0 || connections.getMaxRetries() > 3)
            throw new IllegalArgumentException("模型重试或熔断阈值不正确");
    }

    public Model resolve(String id) {
        var ids = new LinkedHashSet<String>();
        ids.add(id);
        if (connections.isFallbackEnabled()) ids.addAll(fallbackIds());
        var candidates = new ArrayList<ManagedAgentModel.Candidate>();
        for (String modelId : ids) {
            candidates.add(new ManagedAgentModel.Candidate(modelId, models.computeIfAbsent(modelId, this::create),
                    health.computeIfAbsent(modelId, ignored -> new ModelCircuit(connections.getFailureThreshold(),
                            connections.getCircuitCooldown(), connections.getQuotaCooldown()))));
        }
        return new ManagedAgentModel(candidates, GenerateOptions.builder()
                .maxTokens(connections.getMaxOutputTokens()).executionConfig(execution()).build(), connections,
                connections.isFallbackEnabled());
    }

    private static void positive(Duration value) {
        if (value == null || value.isNegative() || value.isZero() || value.compareTo(Duration.ofHours(1)) > 0)
            throw new IllegalArgumentException("模型超时和冷却时间必须在 0 到 1 小时之间");
    }
    private List<String> fallbackIds() {
        var list = connections.getFallbackModels();
        if (list == null || list.isEmpty()) list = List.of(connections.getFallbackModel());
        if (list.stream().anyMatch(id -> id == null || id.isBlank())) throw new IllegalArgumentException("备用模型 ID 不能为空");
        return List.copyOf(new LinkedHashSet<>(list));
    }

    private ExecutionConfig execution() {
        // 开启备用时由路由层负责切换，避免 SDK 重试把等待时间和重复费用叠加。
        return ExecutionConfig.builder().timeout(connections.getTimeout())
                .maxAttempts(connections.isFallbackEnabled() ? 1 : connections.getMaxRetries() + 1).build();
    }

    private ProxyConfig proxy() {
        if (connections.getProxyUrl() == null || connections.getProxyUrl().isBlank()) return null;
        URI uri = URI.create(connections.getProxyUrl());
        if (uri.getHost() == null || uri.getPort() < 1 || uri.getUserInfo() != null
                || uri.getQuery() != null || uri.getFragment() != null
                || !(uri.getPath().isEmpty() || uri.getPath().equals("/"))) throw new IllegalArgumentException("模型代理地址格式不正确");
        return switch (uri.getScheme()) {
            case "http" -> ProxyConfig.http(uri.getHost(), uri.getPort());
            case "socks5" -> ProxyConfig.socks5(uri.getHost(), uri.getPort());
            default -> throw new IllegalArgumentException("模型代理仅支持 HTTP 或 SOCKS5");
        };
    }

    private Model create(String id) {
        var entry = entries().stream().filter(e -> e.id().equals(id)).findFirst()
                .orElseThrow(() -> new IllegalArgumentException("未登记的模型 ID"));
        var config = connection(entry.provider());
        if (!hasKey(config)) throw new IllegalStateException("模型凭证尚未配置：" + entry.provider());
        URI base = URI.create(config.getBaseUrl());
        if (!("https".equals(base.getScheme()) || "http".equals(base.getScheme())) || base.getHost() == null
                || base.getUserInfo() != null || base.getQuery() != null || base.getFragment() != null) {
            throw new IllegalArgumentException("模型基础地址格式不正确");
        }
        var execution = execution();
        var options = GenerateOptions.builder().maxTokens(connections.getMaxOutputTokens())
                .executionConfig(execution).build();
        if (entry.provider().equals("openai")) {
            Map<String, String> headers = connections.getActorAuthorization() == null
                    || connections.getActorAuthorization().isBlank() ? Map.of()
                    : Map.of("x-openai-actor-authorization", connections.getActorAuthorization());
            return OpenAIResponsesChatModel.builder().apiKey(config.getApiKey()).baseUrl(config.getBaseUrl())
                    .modelName(config.getModel()).stream(true).strictTools(false).proxy(proxy())
                    .additionalHeaders(headers).generateOptions(GenerateOptions.builder()
                            .maxTokens(connections.getMaxOutputTokens()).executionConfig(execution)
                            .additionalBodyParam("store", connections.isStore()).build()).build();
        }
        if (entry.provider().equals("dashscope") && base.getPath().contains("compatible-mode")) {
            return OpenAIChatModel.builder().apiKey(config.getApiKey()).baseUrl(config.getBaseUrl())
                    .modelName(config.getModel()).stream(true).proxy(proxy()).generateOptions(options).build();
        }
        var context = ModelCreationContext.builder().apiKey(config.getApiKey())
                .baseUrl(config.getBaseUrl()).stream(true).enableThinking(false)
                .cachePolicy(CachePolicy.DISABLED).component(GenerateOptions.class, options);
        if (proxy() != null) context.component(ProxyConfig.class, proxy());
        return ModelRegistry.resolve(id, context.build());
    }

    private AgentModelProperties.Connection connection(String provider) {
        return switch (provider) {
            case "dashscope" -> connections.getDashscope();
            case "deepseek" -> connections.getDeepseek();
            case "openai" -> connections.getOpenai();
            default -> throw new IllegalArgumentException("未知模型供应商");
        };
    }
    private static boolean hasKey(AgentModelProperties.Connection c) { return c.getApiKey() != null && !c.getApiKey().isBlank(); }
    public List<ModelInfo> entries() {
        return List.of(info("dashscope", "dashscope:", connections.getDashscope(),
                        connections.getDashscope().getBaseUrl().contains("compatible-mode") ? "CHAT_COMPLETIONS" : "DASHSCOPE"),
                info("deepseek", "deepseek:", connections.getDeepseek(), "CHAT_COMPLETIONS"),
                info("openai", "openai-official:", connections.getOpenai(), "RESPONSES"));
    }
    private ModelInfo info(String provider, String prefix, AgentModelProperties.Connection c, String protocol) {
        String id = prefix + c.getModel();
        var circuit = health.get(id);
        var state = circuit == null ? new ModelCircuit.Health("CLOSED", null, 0) : circuit.health();
        return new ModelInfo(id, provider, c.getModel(), protocol, hasKey(c), id.equals(agent.getModel()),
                state.state(), state.lastFailure(), state.retryAfterSeconds());
    }
    public Catalog catalog() {
        var fallback = connections.isFallbackEnabled() ? fallbackIds().stream().filter(id -> !id.equals(agent.getModel())).toList() : List.<String>of();
        return new Catalog(agent.getModel(), connections.isFallbackEnabled(), fallback.isEmpty() ? null : fallback.get(0),
                fallback, connections.getFirstTokenTimeout().toMillis(), entries());
    }
    public record ModelInfo(String id, String provider, String model, String protocol, boolean configured, boolean selected,
                            String healthState, String lastFailure, long retryAfterSeconds) {}
    public record Catalog(String selectedModel, boolean fallbackEnabled, String fallbackModel, List<String> fallbackModels,
                          long firstTokenTimeoutMs, List<ModelInfo> models) {}
}
