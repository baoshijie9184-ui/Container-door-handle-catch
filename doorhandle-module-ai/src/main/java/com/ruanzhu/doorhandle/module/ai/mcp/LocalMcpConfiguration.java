package com.ruanzhu.doorhandle.module.ai.mcp;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;

@Configuration @EnableConfigurationProperties({LocalMcpProperties.class,AgentScopeProperties.class})
@ConditionalOnProperty(prefix="agentscope.mcp",name="enabled",havingValue="true")
public class LocalMcpConfiguration {
    @Bean public FetchMcpRuntime fetchMcpRuntime(LocalMcpProperties properties,ObjectMapper json){return new FetchMcpRuntime(properties,json);}
    @Bean public LocalMcpService localMcpService(JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper json,BusinessUserDirectory users,AgentScopeProperties properties,FetchMcpRuntime runtime){return new LocalMcpService(jdbc,manager,json,users,properties,runtime);}
}
