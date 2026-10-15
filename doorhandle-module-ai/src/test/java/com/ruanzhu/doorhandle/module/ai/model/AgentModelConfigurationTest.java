package com.ruanzhu.doorhandle.module.ai.model;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.api.AgentModelController;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeConfiguration;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.access.AccessDeniedException;
import java.util.List;
import java.util.Map;
import java.nio.file.Path;
import java.nio.file.Files;
import org.springframework.boot.context.properties.bind.*;
import org.springframework.boot.context.properties.source.ConfigurationPropertySources;
import org.springframework.boot.env.YamlPropertySourceLoader;
import org.springframework.core.env.*;
import org.springframework.core.io.FileSystemResource;
import com.ruanzhu.doorhandle.module.ai.config.AgentModelProperties;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class AgentModelConfigurationTest {
    private ApplicationContextRunner runner() {
        return new ApplicationContextRunner().withUserConfiguration(AgentScopeConfiguration.class)
                .withBean(ObjectMapper.class, ObjectMapper::new)
                .withBean(DetectionAgentReadApi.class, () -> mock(DetectionAgentReadApi.class))
                .withBean(ResourceAgentReadApi.class, () -> mock(ResourceAgentReadApi.class))
                .withBean(ModelAgentReadApi.class, () -> mock(ModelAgentReadApi.class))
                .withPropertyValues("agentscope.ai.enabled=true", "agentscope.ai.model=openai-official:fixture-model",
                        "agentscope.models.openai.api-key=fixture-bound-secret", "agentscope.models.openai.model=fixture-model");
    }
    @Test void bindsSpringCredentialsAndExposesOnlyAnAuthenticatedSanitizedCatalog() {
        runner().run(context -> {
            assertThat(context).hasNotFailed();
            var models = context.getBean(AgentModelService.class);
            var controller = new AgentModelController(models);
            var roles = List.of(new SimpleGrantedAuthority("ROLE_INSPECTOR"));
            var auth = new UsernamePasswordAuthenticationToken(new TenantPrincipal(1L, "alice", "", roles), null, roles);
            assertThat(controller.catalog(auth).selectedModel()).isEqualTo("openai-official:fixture-model");
            assertThat(controller.catalog(auth).models()).filteredOn(model -> model.selected()).singleElement()
                    .satisfies(model -> assertThat(model.configured()).isTrue());
            assertThatThrownBy(() -> controller.catalog(null)).isInstanceOf(AccessDeniedException.class);
            var otherRoles = List.of(new SimpleGrantedAuthority("ROLE_USER"));
            var other = new UsernamePasswordAuthenticationToken(new TenantPrincipal(2L, "bob", "", otherRoles), null, otherRoles);
            assertThatThrownBy(() -> controller.catalog(other)).isInstanceOf(AccessDeniedException.class);
            assertThat(context.getBean(ObjectMapper.class).writeValueAsString(controller.catalog(auth)))
                    .doesNotContain("fixture-bound-secret", "apiKey", "Authorization", "baseUrl");
        });
    }
    @Test void invalidDefaultOrMissingCredentialsStopsStartup() {
        runner().withPropertyValues("agentscope.ai.model=unregistered:model").run(context -> assertThat(context).hasFailed());
        runner().withPropertyValues("agentscope.models.openai.api-key=").run(context -> assertThat(context).hasFailed());
    }
    @Test void validatesBackupConnectionsAndLatencyBudgetsBeforeStartup() {
        runner().withPropertyValues("agentscope.models.fallback-enabled=true",
                "agentscope.models.fallback-models=deepseek:deepseek-flash,dashscope:qwen-plus",
                "agentscope.models.deepseek.api-key=fixture-deepseek", "agentscope.models.dashscope.api-key=fixture-dashscope",
                "agentscope.models.first-token-timeout=8s", "agentscope.models.failure-threshold=3",
                "agentscope.models.quota-cooldown=10m").run(context -> {
                    assertThat(context).hasNotFailed();
                    var catalog = context.getBean(AgentModelService.class).catalog();
                    assertThat(catalog.fallbackModels()).containsExactly("deepseek:deepseek-flash", "dashscope:qwen-plus");
                    assertThat(catalog.firstTokenTimeoutMs()).isEqualTo(8000);
                });
        runner().withPropertyValues("agentscope.models.fallback-enabled=true").run(context -> assertThat(context).hasFailed());
        runner().withPropertyValues("agentscope.models.first-token-timeout=0s").run(context -> assertThat(context).hasFailed());
        runner().withPropertyValues("agentscope.models.first-token-timeout=70s").run(context -> assertThat(context).hasFailed());
        runner().withPropertyValues("agentscope.models.failure-threshold=0").run(context -> assertThat(context).hasFailed());
    }
    @Test void productionYamlBindsOrderedBackupsAndLatencySettingsFromEnvironment() throws Exception {
        Path root = Path.of("").toAbsolutePath();
        while (root != null && !Files.exists(root.resolve("doorhandle-server/src/main/resources/application.yml"))) root = root.getParent();
        assertThat(root).isNotNull();
        var environment = new StandardEnvironment();
        var sources = environment.getPropertySources();
        sources.remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
        sources.remove(StandardEnvironment.SYSTEM_PROPERTIES_PROPERTY_SOURCE_NAME);
        sources.addFirst(new MapPropertySource("fixture-env", Map.of(
                "AGENTSCOPE_AI_MODEL", "openai-official:fixture-model", "OPENAI_MODEL", "fixture-model", "OPENAI_API_KEY", "fixture-key",
                "AGENT_MODEL_FALLBACK_ENABLED", "true", "AGENT_MODEL_FALLBACK_MODELS", "deepseek:deepseek-flash,dashscope:fixture-dashscope",
                "DASHSCOPE_MODEL", "fixture-dashscope", "DASHSCOPE_API_KEY", "fixture-dashscope-key", "DEEPSEEK_API_KEY", "fixture-deepseek-key",
                "AGENT_MODEL_FIRST_TOKEN_TIMEOUT", "12s", "AGENT_MODEL_QUOTA_COOLDOWN", "8m")));
        for (var source : new YamlPropertySourceLoader().load("application", new FileSystemResource(root.resolve("doorhandle-server/src/main/resources/application.yml")))) sources.addLast(source);
        var binder = new Binder(ConfigurationPropertySources.get(environment), new PropertySourcesPlaceholdersResolver(environment));
        var connections = binder.bind("agentscope.models", Bindable.of(AgentModelProperties.class)).get();
        var agent = binder.bind("agentscope.ai", Bindable.of(AgentScopeProperties.class)).get();
        assertThat(connections.getQuotaCooldown()).isEqualTo(java.time.Duration.ofMinutes(8));
        var models = new AgentModelService(connections, agent); models.resolve(agent.getModel());
        assertThat(models.catalog().fallbackModels()).containsExactly("deepseek:deepseek-flash", "dashscope:fixture-dashscope");
        assertThat(models.catalog().firstTokenTimeoutMs()).isEqualTo(12000);
    }
}
