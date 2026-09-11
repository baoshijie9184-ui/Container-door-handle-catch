package com.ruanzhu.doorhandle.module.app.config;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.config.YamlPropertiesFactoryBean;
import org.springframework.core.io.FileSystemResource;

import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.Objects;
import java.util.Properties;

import static org.assertj.core.api.Assertions.assertThat;

class ProductionConfigDefaultsTest {

    private static final FileSystemResource APPLICATION_YAML = new FileSystemResource(
            Path.of("..", "doorhandle-server", "src", "main", "resources", "application.yml"));

    @Test
    void applicationNameRemainsDoorHandleCatchInYaml() {
        YamlPropertiesFactoryBean yaml = new YamlPropertiesFactoryBean();
        yaml.setResources(APPLICATION_YAML);
        Properties properties = Objects.requireNonNull(yaml.getObject());

        assertThat(properties.getProperty("spring.application.name")).isEqualTo("DoorHandleCatch");
    }

    @Test
    void applicationConfigDoesNotShipWithRootDatabasePasswordOrJwtSecret() throws Exception {
        String config = APPLICATION_YAML
                .getContentAsString(StandardCharsets.UTF_8);

        assertThat(config).doesNotContain("DB_PASSWORD:root");
        assertThat(config).doesNotContain("JWT_SECRET:doorhandlecatch");
    }

    @Test
    void businessSeedImportIsExplicitlyOptIn() throws Exception {
        String config = APPLICATION_YAML
                .getContentAsString(StandardCharsets.UTF_8);

        assertThat(config).contains("APP_BUSINESS_SEED_ENABLED:false");
        assertThat(config).contains("business-seed-new-features.sql");
        assertThat(config).contains("business-seed-more-features.sql");
        assertThat(config).contains("business-seed-trace-rich.sql");
    }
}
