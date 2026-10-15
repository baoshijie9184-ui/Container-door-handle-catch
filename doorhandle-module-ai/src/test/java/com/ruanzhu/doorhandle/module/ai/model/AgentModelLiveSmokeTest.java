package com.ruanzhu.doorhandle.module.ai.model;

import com.ruanzhu.doorhandle.module.ai.config.AgentModelProperties;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import io.agentscope.core.ReActAgent;
import io.agentscope.core.state.InMemoryAgentStateStore;
import io.agentscope.core.tool.*;
import io.agentscope.core.message.ToolResultBlock;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.boot.context.properties.bind.*;
import org.springframework.boot.context.properties.source.ConfigurationPropertySources;
import org.springframework.boot.env.YamlPropertySourceLoader;
import org.springframework.core.env.*;
import org.springframework.core.io.FileSystemResource;
import reactor.core.publisher.Mono;
import java.nio.file.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;

/** Opt-in, small live provider test. Default test runs never consume model quota. */
@EnabledIfSystemProperty(named = "agent.model.live", matches = "true")
class AgentModelLiveSmokeTest {
    private AgentModelService configuredModels() throws Exception {
        Path root = Path.of(System.getProperty("agent.model.project"));
        Map<String, Object> dotenv = new HashMap<>();
        for (String line : Files.readAllLines(root.resolve(".env"))) {
            if (line.matches("[A-Z][A-Z0-9_]*=.*")) {
                int separator = line.indexOf('=');
                dotenv.put(line.substring(0, separator), line.substring(separator + 1).trim());
            }
        }
        var environment = new StandardEnvironment();
        var properties = environment.getPropertySources();
        properties.addLast(new MapPropertySource("local-dotenv", dotenv));
        for (var source : new YamlPropertySourceLoader().load("application", new FileSystemResource(
                root.resolve("doorhandle-server/src/main/resources/application.yml")))) properties.addLast(source);
        var binder = new Binder(ConfigurationPropertySources.get(environment), new PropertySourcesPlaceholdersResolver(environment));
        var connections = binder.bind("agentscope.models", Bindable.of(AgentModelProperties.class)).get();
        var agentConfig = binder.bind("agentscope.ai", Bindable.of(AgentScopeProperties.class)).get();
        connections.setMaxRetries(0); connections.setMaxOutputTokens(256);
        // 该测试验证所选模型，禁止备用成功被误报为默认模型成功。
        connections.setFallbackEnabled(false);
        if (dotenv.containsKey("AGENT_MODEL_PROXY_URL")) {
            assertThat(connections.getProxyUrl()).isEqualTo(dotenv.get("AGENT_MODEL_PROXY_URL"));
        }
        return new AgentModelService(connections, agentConfig);
    }
    @Test void configuredModelRepliesToMinimalText() throws Exception {
        var models = configuredModels();
        var model = models.resolve(models.catalog().selectedModel());
        var chunks = model.stream(List.of(new io.agentscope.core.message.UserMessage("Reply with exactly OK.")), List.of(), null)
                .collectList().block(Duration.ofSeconds(70));
        String text = chunks.stream().flatMap(chunk -> chunk.getContent().stream())
                .filter(block -> block instanceof io.agentscope.core.message.TextBlock)
                .map(block -> ((io.agentscope.core.message.TextBlock) block).getText()).collect(java.util.stream.Collectors.joining());
        assertThat(text.trim()).isEqualTo("OK");
        System.out.println("LIVE_MODEL_TEXT_OK model=" + models.catalog().selectedModel());
    }
    @Test void configuredSdkModelStreamsInvokesToolAndConsumesItsResult() throws Exception {
        var models = configuredModels();
        var model = models.resolve(models.catalog().selectedModel());
        var calls = new AtomicInteger();
        var toolkit = new Toolkit();
        toolkit.registerAgentTool(new AgentTool() {
            public String getName() { return "probe_model_configuration"; }
            public String getDescription() { return "返回模型接入验证标记，无业务写入"; }
            public boolean isReadOnly() { return true; }
            public Map<String, Object> getParameters() { return Map.of("type", "object", "properties", Map.of(), "additionalProperties", false); }
            public Mono<ToolResultBlock> callAsync(ToolCallParam input) {
                calls.incrementAndGet();
                System.out.println("LIVE_MODEL_PROBE_TOOL_CALLED");
                return Mono.just(ToolResultBlock.text("MODEL_SMOKE_TEST_OK"));
            }
        });
        var agent = ReActAgent.builder().name("model-configuration-smoke").model(model).toolkit(toolkit)
                .sysPrompt("You verify model connectivity. You must call probe_model_configuration exactly once, then reply with its returned text. Do not invent a tool result.")
                .maxIters(3).enableMetaTool(false).enableTaskList(false).stateStore(new InMemoryAgentStateStore()).build();
        var reply = agent.call("Call the verification tool and return its result.").block(Duration.ofSeconds(80));
        assertThat(calls.get()).isEqualTo(1);
        assertThat(reply.getTextContent()).contains("MODEL_SMOKE_TEST_OK");
        System.out.println("LIVE_MODEL_TOOL_ROUNDTRIP_OK model=" + models.catalog().selectedModel());
    }
}
