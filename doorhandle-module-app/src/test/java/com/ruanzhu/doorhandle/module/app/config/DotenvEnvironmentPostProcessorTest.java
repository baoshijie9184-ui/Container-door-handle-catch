package com.ruanzhu.doorhandle.module.app.config;

import org.junit.jupiter.api.Test;
import org.springframework.core.env.MapPropertySource;
import org.springframework.mock.env.MockEnvironment;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class DotenvEnvironmentPostProcessorTest {

    @Test
    void existingHigherPriorityPropertyTakesPrecedenceOverDotenv() {
        MockEnvironment environment = new MockEnvironment();
        environment.getPropertySources().addFirst(new MapPropertySource(
                "commandLineProperties",
                Map.of("DB_USERNAME", "from-command-line")));

        DotenvEnvironmentPostProcessor.addDotenvProperties(
                environment,
                Map.of("DB_USERNAME", "from-dotenv"));

        assertThat(environment.getProperty("DB_USERNAME")).isEqualTo("from-command-line");
        assertThat(environment.getPropertySources().get("dotenvProperties")).isNotNull();
    }

    @Test
    void emptyDotenvDoesNotRegisterPropertySource() {
        MockEnvironment environment = new MockEnvironment();

        DotenvEnvironmentPostProcessor.addDotenvProperties(environment, Map.of());

        assertThat(environment.getPropertySources().contains("dotenvProperties")).isFalse();
    }

    @Test
    void dotenvProvidesFallbackValueWhenNoHigherPriorityPropertyExists() {
        MockEnvironment environment = new MockEnvironment();

        DotenvEnvironmentPostProcessor.addDotenvProperties(
                environment,
                Map.of("DB_USERNAME", "from-dotenv"));

        assertThat(environment.getProperty("DB_USERNAME")).isEqualTo("from-dotenv");
    }
}
