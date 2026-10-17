package com.ruanzhu.doorhandle.module.ai.context;

import com.ruanzhu.doorhandle.module.ai.agent.RoleAgentFactory;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory;
import io.agentscope.core.model.Model;
import org.junit.jupiter.api.Test;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.context.annotation.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class ContextCompactionConfigurationTest {
    @Configuration(proxyBeanMethods=false) @EnableConfigurationProperties(AgentScopeProperties.class)
    static class Config {
        @Bean RoleAgentFactory factory(AgentScopeProperties properties){return new RoleAgentFactory(properties,mock(BusinessToolkitFactory.class),id->mock(Model.class));}
    }
    final ApplicationContextRunner runner=new ApplicationContextRunner().withUserConfiguration(Config.class);
    @Test void defaultsAreOffAndNestedSpringSettingsBind(){
        runner.run(ctx->{assertThat(ctx).hasNotFailed();assertThat(ctx.getBean(AgentScopeProperties.class).getContextCompaction().isEnabled()).isFalse();});
        runner.withPropertyValues("agentscope.ai.context-compaction.enabled=true","agentscope.ai.context-compaction.keep-messages=8","agentscope.ai.context-compaction.trigger-tokens=16000").run(ctx->{
            assertThat(ctx).hasNotFailed();var settings=ctx.getBean(AgentScopeProperties.class).getContextCompaction();
            assertThat(settings.isEnabled()).isTrue();assertThat(settings.getKeepMessages()).isEqualTo(8);assertThat(settings.getTriggerTokens()).isEqualTo(16000);
        });
    }
    @Test void invalidSettingsFailAtStartup(){
        runner.withPropertyValues("agentscope.ai.context-compaction.keep-messages=32").run(ctx->{assertThat(ctx).hasFailed();assertThat(ctx.getStartupFailure()).hasRootCauseMessage("上下文压缩配置超出范围");});
    }
}
