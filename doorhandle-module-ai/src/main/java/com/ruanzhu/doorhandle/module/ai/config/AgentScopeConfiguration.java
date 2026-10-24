package com.ruanzhu.doorhandle.module.ai.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.agent.RoleAgentFactory;
import com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory;
import com.ruanzhu.doorhandle.module.ai.model.AgentModelService;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;


/** AgentScope 装配入口；业务模块只依赖 Agent 接口，Server 不承载 Agent 实现。 */
@Configuration
@EnableConfigurationProperties({AgentScopeProperties.class, AgentModelProperties.class})
@ConditionalOnProperty(prefix = "agentscope.ai", name = "enabled", havingValue = "true")
public class AgentScopeConfiguration {

    @Bean
    public com.ruanzhu.doorhandle.module.ai.report.AgentReportGateway agentReportGateway(org.springframework.beans.factory.ObjectProvider<QualityReportAgentApi> reports,
            org.springframework.beans.factory.ObjectProvider<com.ruanzhu.doorhandle.module.ai.journal.AgentJournal> journal,org.springframework.beans.factory.ObjectProvider<org.springframework.jdbc.core.JdbcTemplate> jdbc,
            org.springframework.beans.factory.ObjectProvider<org.springframework.transaction.PlatformTransactionManager> transactions,ObjectMapper json){
        if(reports.getIfAvailable()==null||journal.getIfAvailable()==null||jdbc.getIfAvailable()==null||transactions.getIfAvailable()==null)return null;
        return new com.ruanzhu.doorhandle.module.ai.report.AgentReportGateway(reports.getObject(),journal.getObject(),jdbc.getObject(),transactions.getObject(),json);
    }

    @Bean
    public BusinessToolkitFactory businessToolkitFactory(DetectionAgentReadApi detection,
            ResourceAgentReadApi resources, ModelAgentReadApi models, ObjectMapper json, org.springframework.beans.factory.ObjectProvider<com.ruanzhu.doorhandle.module.ai.action.AgentActionService> actions,
            org.springframework.beans.factory.ObjectProvider<com.ruanzhu.doorhandle.module.ai.report.AgentReportGateway> reports,
            org.springframework.beans.factory.ObjectProvider<SystemHealthReadApi> health) {
        return new BusinessToolkitFactory(detection, resources, models, json, actions.getIfAvailable(),reports.getIfAvailable(),health.getIfAvailable());
    }

    @Bean
    public AgentModelService agentModelService(AgentModelProperties connections, AgentScopeProperties properties,org.springframework.beans.factory.ObjectProvider<com.ruanzhu.doorhandle.module.ai.model.ModelConfigurationService> configurations,org.springframework.beans.factory.ObjectProvider<org.springframework.data.redis.core.StringRedisTemplate> redis) {
        var models = new AgentModelService(connections, properties);
        models.setConfigurations(configurations.getIfAvailable());
        if(configurations.getIfAvailable()!=null)models.setCircuitRedis(redis.getObject());
        models.resolve(models.currentDefault()); // Validate without generating a provider request.
        return models;
    }

    @Bean
    public RoleAgentFactory roleAgentFactory(AgentScopeProperties properties, BusinessToolkitFactory toolkits,
            AgentModelService models,org.springframework.beans.factory.ObjectProvider<com.ruanzhu.doorhandle.module.ai.evolution.SkillEvolutionService> evolution,
            org.springframework.beans.factory.ObjectProvider<com.ruanzhu.doorhandle.module.ai.mcp.LocalMcpService> mcp,
            org.springframework.beans.factory.ObjectProvider<com.ruanzhu.doorhandle.module.ai.context.DurableContextStore> contexts) {
        var factory=new RoleAgentFactory(properties, toolkits, models::resolve,evolution.getIfAvailable(),mcp.getIfAvailable());factory.setVersionedModels(models::resolveAt,models::currentDefault);factory.setDurableContexts(contexts.getIfAvailable());return factory;
    }
}
