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
    @Bean public FetchMcpRuntime fetchMcpRuntime(LocalMcpProperties properties,ObjectMapper json,JdbcTemplate jdbc,PlatformTransactionManager manager){return new FetchMcpRuntime(properties,json,new FetchImageRegistry(jdbc,manager,properties.isSharedImageCleanupEnabled()));}
    @Bean public LocalMcpService localMcpService(JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper json,BusinessUserDirectory users,AgentScopeProperties properties,FetchMcpRuntime runtime,
            org.springframework.beans.factory.ObjectProvider<com.ruanzhu.doorhandle.module.ai.research.ResearchEvidenceService> research,LocalMcpProperties mcp){
        if(mcp.isExecutionReceiptsEnabled()&&!mcp.isGateway()&&!mcp.isNativeProcessEnabled())throw new IllegalStateException("MCP_DURABLE_STDIO_UNAVAILABLE");
        if(mcp.isNativeProcessEnabled()&&!mcp.isGateway()&&(!mcp.isExecutionReceiptsEnabled()||!System.getProperty("os.name","").toLowerCase(java.util.Locale.ROOT).contains("linux")))throw new IllegalStateException("MCP_NATIVE_RECEIPTS_REQUIRE_LINUX_AND_LEDGER");
        if(mcp.isNativeInstallEnabled()&&(mcp.isGateway()||!mcp.isNativeProcessEnabled()||!mcp.isExecutionReceiptsEnabled()||!mcp.isDurableInstallEnabled()||!mcp.isLifecycleEnabled()||!mcp.isInstallReconciliationEnabled()))throw new IllegalStateException("MCP_NATIVE_INSTALL_REQUIRES_DURABLE_RECEIPTS");
        if(mcp.isLifecycleEnabled()&&(!mcp.isGateway()&&!mcp.isNativeInstallEnabled()||!mcp.isExecutionReceiptsEnabled()||!mcp.isDurableInstallEnabled()))throw new IllegalStateException("MCP_LIFECYCLE_REQUIRES_DURABLE_INSTALLER");
        if(mcp.isInstallReconciliationEnabled()&&!mcp.isLifecycleEnabled())throw new IllegalStateException("MCP_INSTALL_RECONCILIATION_REQUIRES_LIFECYCLE");
        if(mcp.isSharedImageCleanupEnabled()&&(!mcp.isGateway()||!mcp.isLifecycleEnabled()||!mcp.isInstallReconciliationEnabled()))throw new IllegalStateException("MCP_IMAGE_CLEANUP_REQUIRES_DURABLE_GATEWAY");
        var workers=mcp.isInstallReconciliationEnabled()?new McpInstallWorkerEvidence(jdbc,runtime,mcp.getInstallProcessNodeId()):null;
        var lifecycle=mcp.isLifecycleEnabled()?new FetchInstallationLifecycle(jdbc,manager,json,runtime,java.nio.file.Path.of(properties.getWorkspace().replace("${user.dir}",System.getProperty("user.dir"))),mcp.getStorageQuotaBytes(),workers):null;
        return new LocalMcpService(jdbc,manager,json,users,properties,runtime,research.getIfAvailable(),mcp.isDurableInstallEnabled()?new PersistentMcpInstallQueue(jdbc):null,mcp.isExecutionReceiptsEnabled()?new McpExecutionLedger(jdbc,manager,json,runtime.transport(),runtime.imageRegistry()):null,lifecycle);
    }
}
