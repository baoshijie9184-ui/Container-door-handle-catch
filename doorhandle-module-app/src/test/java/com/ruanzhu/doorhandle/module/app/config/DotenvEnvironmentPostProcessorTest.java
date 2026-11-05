package com.ruanzhu.doorhandle.module.app.config;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.core.env.MapPropertySource;
import org.springframework.mock.env.MockEnvironment;

import java.util.Map;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class DotenvEnvironmentPostProcessorTest {
    @TempDir Path temporary;

    @Test
    void composeFileIsNotAnImplicitJavaFile() {
        var environment = new MockEnvironment().withProperty("DOORHANDLE_ENV_FILE", "/host-only/private/cloud.env");
        new DotenvEnvironmentPostProcessor().postProcessEnvironment(environment, null);
        assertThat(environment.getPropertySources().contains("dotenvProperties")).isFalse();
    }

    @Test
    void defaultStartupDoesNotLoadWorkingDirectoryDotenv() {
        var environment = new MockEnvironment();
        new DotenvEnvironmentPostProcessor().postProcessEnvironment(environment, null);
        assertThat(environment.getPropertySources().contains("dotenvProperties")).isFalse();
        assertThat(environment.getProperty("DB_URL")).isNull();
    }

    @Test
    void explicitServerFileLoadsWithoutOverridingDeploymentEnvironment() throws Exception {
        Path file = temporary.resolve("server.env");
        Files.writeString(file, "DB_URL=jdbc:mysql://mysql:3306/fixture\nDB_USERNAME=fixture-user\n");
        var environment = new MockEnvironment().withProperty("DOORHANDLE_JAVA_ENV_FILE", file.toString())
                .withProperty("DB_USERNAME", "deployment-user");
        new DotenvEnvironmentPostProcessor().postProcessEnvironment(environment, null);
        assertThat(environment.getProperty("DB_URL")).isEqualTo("jdbc:mysql://mysql:3306/fixture");
        assertThat(environment.getProperty("DB_USERNAME")).isEqualTo("deployment-user");
    }

    @Test
    void relativeOrMissingExplicitConfigurationFailsClosed() {
        for (String file : new String[]{".env", temporary.resolve("missing.env").toString()}) {
            var environment = new MockEnvironment().withProperty("DOORHANDLE_JAVA_ENV_FILE", file);
            assertThatThrownBy(() -> new DotenvEnvironmentPostProcessor().postProcessEnvironment(environment, null))
                    .isInstanceOf(IllegalStateException.class);
        }
    }

    @Test
    void malformedExplicitConfigurationIsRejectedWithoutLeakingValues() throws Exception {
        Path file = temporary.resolve("malformed.env");
        Files.writeString(file, "secret-without-an-assignment\n");
        var environment = new MockEnvironment().withProperty("DOORHANDLE_JAVA_ENV_FILE", file.toString());
        assertThatThrownBy(() -> new DotenvEnvironmentPostProcessor().postProcessEnvironment(environment, null))
                .isInstanceOf(IllegalStateException.class)
                .hasMessage("Unable to load DOORHANDLE_JAVA_ENV_FILE").hasNoCause();
    }

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
