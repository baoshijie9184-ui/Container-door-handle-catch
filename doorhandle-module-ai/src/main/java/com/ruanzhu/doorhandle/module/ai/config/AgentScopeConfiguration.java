package com.ruanzhu.doorhandle.module.ai.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.agent.RoleAgentFactory;
import com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;


/** AgentScope 装配入口；业务模块只依赖 Agent 接口，Server 不承载 Agent 实现。 */
@Configuration
@EnableConfigurationProperties(AgentScopeProperties.class)
@ConditionalOnProperty(prefix = "agentscope.ai", name = "enabled", havingValue = "true")
public class AgentScopeConfiguration {

    @Bean
    public BusinessToolkitFactory businessToolkitFactory(DetectionAgentReadApi detection,
            ResourceAgentReadApi resources, ModelAgentReadApi models, ObjectMapper json) {
        return new BusinessToolkitFactory(detection, resources, models, json);
    }

    @Bean
    public RoleAgentFactory roleAgentFactory(AgentScopeProperties properties, BusinessToolkitFactory toolkits) {
        return new RoleAgentFactory(properties, toolkits);
    }
}
