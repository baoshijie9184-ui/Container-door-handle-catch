package com.ruanzhu.doorhandle.module.ai.model;

import com.ruanzhu.doorhandle.module.ai.config.AgentModelProperties;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import io.agentscope.core.model.*;
import io.agentscope.core.model.transport.ProxyConfig;
import io.agentscope.extensions.model.openai.OpenAIChatModel;
import io.agentscope.extensions.model.openaiofficial.OpenAIResponsesIoBridge;
import java.net.URI;
import java.util.List;
import java.util.Map;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.time.Duration;
import java.util.concurrent.ConcurrentHashMap;

/** Explicit Spring credential binding; no JVM environment or shared registry mutation. */
public class AgentModelService implements AutoCloseable {
    private final AgentModelProperties connections;
    private final AgentScopeProperties agent;
    private final Map<String, Model> models = new ConcurrentHashMap<>();
    private final Map<String, ModelCircuit> health = new ConcurrentHashMap<>();
    private boolean closed;
    private ModelConfigurationService configurations;
    private static final int MAX_CACHED_VERSIONS = 16;
    private final Map<Long, VersionClient> versions = new java.util.LinkedHashMap<>(16, .75f, true);
    private final List<AutoCloseable> ownedResources = new ArrayList<>();
    private static final class VersionClient {
        final AgentModelService client;
        int activeStreams;
        VersionClient(AgentModelService client) { this.client = client; }
    }
    private java.util.function.Consumer<String> configurationGuard=id->{};
    private org.springframework.data.redis.core.StringRedisTemplate circuitRedis;
    private long circuitRevision;
    public void setCircuitRedis(org.springframework.data.redis.core.StringRedisTemplate value){circuitRedis=value;}
    public void setConfigurations(ModelConfigurationService value){configurations=value;}
    public String currentDefault(){return configurations==null?agent.getModel():configurations.active().defaultModel();}
    public Model resolveAt(String id,long revision){
        if(configurations==null)return resolve(id);
        long version=revision==0?configurations.active().version():revision;
        configurations.assertUsable(version,id);
        return new Model(){
            public String getModelName(){return id;}
            public reactor.core.publisher.Flux<ChatResponse> stream(List<io.agentscope.core.message.Msg> input,List<ToolSchema> tools,GenerateOptions options){
                return reactor.core.publisher.Flux.using(() -> lease(version), holder -> {
                    configurations.assertUsable(version,id);
                    return holder.client.resolve(id).stream(input,tools,options);
                }, AgentModelService.this::release);
            }
            public int getContextWindowSize(){return metadata(version,id).getContextWindowSize();}
            public boolean supportsNativeStructuredOutput(){return metadata(version,id).supportsNativeStructuredOutput();}
            public boolean supportsNativeStructuredOutputWithTools(){return metadata(version,id).supportsNativeStructuredOutputWithTools();}
        };
    }
    private synchronized AgentModelService versionClient(long revision){
        if(closed)throw new IllegalStateException("模型服务已关闭");
        var existing = versions.get(revision);
        if(existing != null) return existing.client;
        if(versions.size() >= MAX_CACHED_VERSIONS){
            var iterator = versions.entrySet().iterator();
            boolean evicted = false;
            while(iterator.hasNext()){
                var candidate = iterator.next().getValue();
                if(candidate.activeStreams == 0){ iterator.remove(); candidate.client.close(); evicted = true; break; }
            }
            if(!evicted)throw new IllegalStateException("模型版本执行资源已满，请稍后重试");
        }
        var snapshot=configurations.runtime(revision);var settings=new AgentScopeProperties();settings.setModel(snapshot.document().defaultModel());
        var client=new AgentModelService(snapshot.properties(),settings);
        if(circuitRedis==null)throw new RedisModelCircuit.Unavailable();
        client.circuitRedis=circuitRedis;client.circuitRevision=revision;
        client.configurationGuard=id->configurations.assertUsable(revision,id);
        versions.put(revision,new VersionClient(client));
        return client;
    }
    private synchronized VersionClient lease(long revision){versionClient(revision);var holder=versions.get(revision);holder.activeStreams++;return holder;}
    private synchronized void release(VersionClient holder){holder.activeStreams--;}
    private synchronized Model metadata(long revision,String id){return versionClient(revision).resolve(id);}
    private Model guarded(String id,Model delegate){
        if(delegate instanceof AutoCloseable resource)ownedResources.add(resource);
        return new Model(){
            public String getModelName(){return delegate.getModelName();}
            public int getContextWindowSize(){return delegate.getContextWindowSize();}
            public boolean supportsNativeStructuredOutput(){return delegate.supportsNativeStructuredOutput();}
            public boolean supportsNativeStructuredOutputWithTools(){return delegate.supportsNativeStructuredOutputWithTools();}
            public reactor.core.publisher.Flux<ChatResponse> stream(List<io.agentscope.core.message.Msg> input,List<ToolSchema> tools,GenerateOptions options){return reactor.core.publisher.Flux.defer(()->{configurationGuard.accept(id);return delegate.stream(input,tools,options);});}
        };
    }

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

    public synchronized Model resolve(String id) {
        if(configurations!=null)return resolveAt(id,configurations.active().version());
        if (closed) throw new IllegalStateException("模型服务已关闭");
        var ids = new LinkedHashSet<String>();
        ids.add(id);
        if (connections.isFallbackEnabled()) ids.addAll(fallbackIds());
        var candidates = new ArrayList<ManagedAgentModel.Candidate>();
        for (String modelId : ids) {
            var entry = entries().stream().filter(info -> info.id().equals(modelId)).findFirst()
                    .orElseThrow(() -> new IllegalArgumentException("未登记的模型 ID"));
            candidates.add(new ManagedAgentModel.Candidate(modelId, entry.provider(), models.computeIfAbsent(modelId, key->guarded(key,create(key))),
                    health.computeIfAbsent(modelId, this::circuit)));
        }
        return new ManagedAgentModel(candidates, GenerateOptions.builder()
                .maxTokens(connections.getMaxOutputTokens()).executionConfig(execution()).build(), connections,
                connections.isFallbackEnabled() || circuitRedis != null);
    }
    private ModelCircuit circuit(String id){return circuitRedis==null?new ModelCircuit(connections.getFailureThreshold(),connections.getCircuitCooldown(),connections.getQuotaCooldown()):new RedisModelCircuit(circuitRedis,circuitRevision,id,connections.getFailureThreshold(),connections.getCircuitCooldown(),connections.getQuotaCooldown(),connections.getTimeout());}

    private static void positive(Duration value) {
        if (value == null || value.isNegative() || value.isZero() || value.compareTo(Duration.ofHours(1)) > 0)
            throw new IllegalArgumentException("模型超时和冷却时间必须在 0 到 1 小时之间");
    }
    List<String> fallbackIds() {
        var list = connections.getFallbackModels();
        if (list == null || list.isEmpty()) list = List.of(connections.getFallbackModel());
        list = new ArrayList<>(list);
        if (connections.getAdditionalFallbackModels() != null) list.addAll(connections.getAdditionalFallbackModels());
        if (list.stream().anyMatch(id -> id == null || id.isBlank())) throw new IllegalArgumentException("备用模型 ID 不能为空");
        return List.copyOf(new LinkedHashSet<>(list));
    }

    private ExecutionConfig execution() {
        // 开启备用时由路由层负责切换，避免 SDK 重试把等待时间和重复费用叠加。
        return ExecutionConfig.builder().timeout(connections.getTimeout())
                .maxAttempts(connections.isFallbackEnabled() ? 1 : connections.getMaxRetries() + 1).build();
    }

    private ProxyConfig proxy() {
        if (gatewayEnabled()) return null;
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
        String baseUrl = effectiveBaseUrl(entry.provider(), base);
        var execution = execution();
        var options = GenerateOptions.builder().maxTokens(connections.getMaxOutputTokens())
                .executionConfig(execution).build();
        if (entry.provider().equals("openai")) {
            Map<String, String> headers = connections.getActorAuthorization() == null
                    || connections.getActorAuthorization().isBlank() ? Map.of()
                    : Map.of("x-openai-actor-authorization", connections.getActorAuthorization());
            return OpenAIResponsesIoBridge.create(config.getApiKey(),baseUrl,entry.model(),proxy(),headers,
                    GenerateOptions.builder()
                            .maxTokens(connections.getMaxOutputTokens()).executionConfig(execution)
                            .additionalBodyParam("store", connections.isStore()).build());
        }
        if (entry.provider().equals("dashscope") && base.getPath().contains("compatible-mode")) {
            // Qwen 混合思考模型在非思考模式下兼容强制工具选择及非流式摘要调用。
            if (entry.model().startsWith("qwen3.")) options = GenerateOptions.builder()
                    .maxTokens(connections.getMaxOutputTokens()).executionConfig(execution)
                    .additionalBodyParam("enable_thinking", false).build();
            return OpenAIChatModel.builder().apiKey(config.getApiKey()).baseUrl(baseUrl)
                    .modelName(entry.model()).stream(true).proxy(proxy()).generateOptions(options).build();
        }
        var context = ModelCreationContext.builder().apiKey(config.getApiKey())
                .baseUrl(baseUrl).stream(true).enableThinking(false)
                .cachePolicy(CachePolicy.DISABLED).component(GenerateOptions.class, options);
        if (proxy() != null) context.component(ProxyConfig.class, proxy());
        return ModelRegistry.resolve(id, context.build());
    }

    private boolean gatewayEnabled() { return connections.getGatewayBaseUrl() != null && !connections.getGatewayBaseUrl().isBlank(); }
    String effectiveBaseUrl(String provider, URI original) {
        if (!gatewayEnabled()) return original.toString();
        URI gateway = URI.create(connections.getGatewayBaseUrl());
        if (!("http".equals(gateway.getScheme()) || "https".equals(gateway.getScheme())) || gateway.getHost() == null
                || gateway.getUserInfo() != null || gateway.getQuery() != null || gateway.getFragment() != null
                || !(gateway.getPath().isEmpty() || gateway.getPath().equals("/")))
            throw new IllegalArgumentException("AI 网关地址格式不正确");
        if (!List.of("openai", "deepseek", "dashscope").contains(provider)) throw new IllegalArgumentException("未知模型供应商");
        return gateway.toString().replaceAll("/$", "") + "/llm/" + provider + original.getRawPath();
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
    @Override public synchronized void close() {
        if (closed) return;
        closed=true;
        try {
            for (AutoCloseable resource:ownedResources)try{resource.close();}catch(Exception ignored){/* Never log provider exception bodies. */}
        } finally { ownedResources.clear();models.clear();versions.values().forEach(holder->holder.client.close());versions.clear(); }
    }
    public List<ModelInfo> entries() {
        if(configurations!=null){var active=configurations.active();var enabled=configurations.enabledIds(active.version());return versionClient(active.version()).entries().stream().map(info->new ModelInfo(info.id(),info.provider(),info.model(),info.protocol(),info.configured()&&enabled.contains(info.id()),info.id().equals(active.defaultModel()),info.healthState(),info.lastFailure(),info.retryAfterSeconds())).toList();}
        var result = new ArrayList<ModelInfo>();
        register(result, "dashscope", "dashscope:", connections.getDashscope(),
                connections.getDashscope().getBaseUrl().contains("compatible-mode") ? "CHAT_COMPLETIONS" : "DASHSCOPE");
        register(result, "deepseek", "deepseek:", connections.getDeepseek(), "CHAT_COMPLETIONS");
        register(result, "openai", "openai-official:", connections.getOpenai(), "RESPONSES");
        return List.copyOf(result);
    }
    private void register(List<ModelInfo> result, String provider, String prefix,
                          AgentModelProperties.Connection c, String protocol) {
        var names = new LinkedHashSet<String>();
        names.add(c.getModel());
        if (c.getAdditionalModels() != null) names.addAll(c.getAdditionalModels());
        if (names.size() > 16 || names.stream().anyMatch(name -> name == null
                || !name.matches("[A-Za-z0-9][A-Za-z0-9._/\\-]{0,127}")))
            throw new IllegalArgumentException("每个供应商最多登记 16 个合法模型名称");
        for (String name : names) result.add(info(provider, prefix, c, protocol, name));
    }
    private ModelInfo info(String provider, String prefix, AgentModelProperties.Connection c, String protocol, String model) {
        String id = prefix + model;
        var circuit = circuitRedis==null?health.get(id):health.computeIfAbsent(id,this::circuit);
        var state = circuit == null ? new ModelCircuit.Health("CLOSED", null, 0) : circuit.health();
        return new ModelInfo(id, provider, model, protocol, hasKey(c), id.equals(agent.getModel()),
                state.state(), state.lastFailure(), state.retryAfterSeconds());
    }
    public Catalog catalog() {
        if(configurations!=null){var active=configurations.active();var document=configurations.runtime(active.version()).document();var fallback=document.fallbackEnabled()?document.fallbackModels().stream().filter(id->!id.equals(active.defaultModel())).toList():List.<String>of();return new Catalog(active.defaultModel(),document.fallbackEnabled(),fallback.isEmpty()?null:fallback.get(0),fallback,document.firstTokenTimeoutMs(),entries(),active.version());}
        var fallback = connections.isFallbackEnabled() ? fallbackIds().stream().filter(id -> !id.equals(agent.getModel())).toList() : List.<String>of();
        return new Catalog(agent.getModel(), connections.isFallbackEnabled(), fallback.isEmpty() ? null : fallback.get(0),
                fallback, connections.getFirstTokenTimeout().toMillis(), entries());
    }
    public record ModelInfo(String id, String provider, String model, String protocol, boolean configured, boolean selected,
                            String healthState, String lastFailure, long retryAfterSeconds) {}
    public record Catalog(String selectedModel, boolean fallbackEnabled, String fallbackModel, List<String> fallbackModels,
                          long firstTokenTimeoutMs, List<ModelInfo> models,long configVersion) {
        public Catalog(String selectedModel,boolean fallbackEnabled,String fallbackModel,List<String> fallbackModels,long firstTokenTimeoutMs,List<ModelInfo> models){this(selectedModel,fallbackEnabled,fallbackModel,fallbackModels,firstTokenTimeoutMs,models,0);}
    }
}
