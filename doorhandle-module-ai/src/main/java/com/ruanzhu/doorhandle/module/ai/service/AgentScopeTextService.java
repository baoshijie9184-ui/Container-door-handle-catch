package com.ruanzhu.doorhandle.module.ai.service;

import com.ruanzhu.doorhandle.contracts.agent.AgentTextApi;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import com.ruanzhu.doorhandle.module.ai.model.AgentModelService;
import io.agentscope.core.ReActAgent;
import io.agentscope.core.tool.Toolkit;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;
import java.time.Duration;

@Service
@ConditionalOnProperty(prefix = "agentscope.ai", name = "enabled", havingValue = "true")
public class AgentScopeTextService implements AgentTextApi {
    private final AgentModelService models;
    private final AgentScopeProperties properties;
    public AgentScopeTextService(AgentModelService models, AgentScopeProperties properties) {
        this.models = models; this.properties = properties;
    }
    @Override public String generate(String systemPrompt, String input) {
        if (systemPrompt == null || input == null || systemPrompt.length() > 4000 || input.length() > 12000)
            throw new IllegalArgumentException("知识检索输入不正确");
        try (var agent = ReActAgent.builder().name("knowledge-assistant").sysPrompt(systemPrompt)
                .model(models.resolve(properties.getModel())).toolkit(new Toolkit()).maxIters(1)
                .stateStore(new io.agentscope.core.state.InMemoryAgentStateStore())
                .defaultSessionId(java.util.UUID.randomUUID().toString()).enableMetaTool(false).enableTaskList(false).build()) {
            var reply = agent.call(input).timeout(Duration.ofSeconds(45)).block();
            if (reply == null) throw new IllegalStateException("知识模型没有返回结果");
            return reply.getTextContent();
        }
    }
}
