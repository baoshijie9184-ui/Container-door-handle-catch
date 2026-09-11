package com.ruanzhu.doorhandle.module.ai.config;

import io.agentscope.core.agent.Agent;
import io.agentscope.core.tool.Toolkit;
import io.agentscope.harness.agent.HarnessAgent;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.nio.file.Path;

/** AgentScope 装配入口；业务模块只依赖 Agent 接口，Server 不承载 Agent 实现。 */
@Configuration
@EnableConfigurationProperties(AgentScopeProperties.class)
@ConditionalOnProperty(prefix = "agentscope.ai", name = "enabled", havingValue = "true")
public class AgentScopeConfiguration {

    @Bean
    public Toolkit doorHandleAgentToolkit() {
        return new Toolkit();
    }

    @Bean(name = "doorhandle-assistant")
    public Agent doorHandleAgent(AgentScopeProperties properties, Toolkit toolkit) {
        return HarnessAgent.builder()
                .agentId(properties.getAgentId())
                .name(properties.getName())
                .sysPrompt(properties.getSystemPrompt())
                .model(properties.getModel())
                .toolkit(toolkit)
                .workspace(Path.of(properties.getWorkspace().replace("${user.dir}", System.getProperty("user.dir"))))
                .maxIters(properties.getMaxIters())
                .build();
    }
}
