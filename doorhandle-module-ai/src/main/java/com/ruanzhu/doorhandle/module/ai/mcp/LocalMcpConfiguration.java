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
    @Bean public org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler localMcpInstallScheduler(){var scheduler=new org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler();scheduler.setPoolSize(1);scheduler.setThreadNamePrefix("mcp-install-dispatch-");scheduler.setDaemon(true);scheduler.setRemoveOnCancelPolicy(true);return scheduler;}
    @Bean public FetchMcpRuntime fetchMcpRuntime(LocalMcpProperties properties,ObjectMapper json){return new FetchMcpRuntime(properties,json);}
    @Bean public LocalMcpService localMcpService(JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper json,BusinessUserDirectory users,AgentScopeProperties properties,FetchMcpRuntime runtime,
            org.springframework.beans.factory.ObjectProvider<com.ruanzhu.doorhandle.module.ai.research.ResearchEvidenceService> research,LocalMcpProperties mcp){return new LocalMcpService(jdbc,manager,json,users,properties,runtime,research.getIfAvailable(),mcp.isDurableInstallEnabled()?new PersistentMcpInstallQueue(jdbc):null);}
}
