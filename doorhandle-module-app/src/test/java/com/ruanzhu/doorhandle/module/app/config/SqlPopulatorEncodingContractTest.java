package com.ruanzhu.doorhandle.module.app.config;

import org.junit.jupiter.api.Test;
import com.ruanzhu.doorhandle.module.app.config.properties.BusinessSeedDataProperties;
import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class SqlPopulatorEncodingContractTest {

    private static final Path SOURCE_DIRECTORY = Path.of("src", "main", "java");
    private static final Path CONFIG_DIRECTORY = SOURCE_DIRECTORY.resolve(
            Path.of("com", "ruanzhu", "doorhandle", "module", "app", "config"));

    @Test
    void compactStartupDoesNotConstructCustomSqlPopulators() throws IOException {
        List<String> customPopulators;
        try (var files = Files.walk(SOURCE_DIRECTORY)) {
            customPopulators = files
                    .filter(path -> path.getFileName().toString().endsWith(".java"))
                    .filter(this::containsSqlPopulator)
                    .map(path -> path.getFileName().toString())
                    .sorted()
                    .toList();
        }

        assertThat(customPopulators).isEmpty();
    }

    @Test
    void explicitlyEnablingRetiredSeedStillRejectsLegacyScripts() {
        BusinessSeedDataProperties properties = new BusinessSeedDataProperties();
        properties.setEnabled(true);
        properties.setContinueOnError(true);
        properties.setScripts(List.of("business-seed-new-features.sql"));
        new ApplicationContextRunner().withUserConfiguration(BusinessSeedDataConfig.class)
                .withBean(BusinessSeedDataProperties.class, () -> properties)
                .withPropertyValues("app.business-seed.enabled=true")
                .run(context -> {
                    assertThat(context).hasNotFailed();
                    assertThat(context.getBeansOfType(CommandLineRunner.class)).hasSize(1);
                    assertThatThrownBy(() -> context.getBean(CommandLineRunner.class).run())
                            .isInstanceOf(IllegalStateException.class).hasMessageContaining("已退役").hasMessageContaining("compact");
                });
    }

    @Test
    void defaultAndExplicitlyDisabledSeedDoNotCreateAnImporter() {
        for (String[] values : new String[][] { {}, { "app.business-seed.enabled=false" } }) {
            new ApplicationContextRunner().withUserConfiguration(BusinessSeedDataConfig.class)
                    .withBean(BusinessSeedDataProperties.class, BusinessSeedDataProperties::new)
                    .withPropertyValues(values).run(context -> {
                        assertThat(context).hasNotFailed();
                        assertThat(context).doesNotHaveBean(CommandLineRunner.class);
                    });
        }
    }

    @Test
    void obsoleteDatabaseInitConfigurationDoesNotExist() {
        assertThat(CONFIG_DIRECTORY.resolve("DatabaseInitConfig.java")).doesNotExist();
    }

    private boolean containsSqlPopulator(Path source) {
        try {
            return Files.readString(source, StandardCharsets.UTF_8)
                    .contains("new ResourceDatabasePopulator(");
        } catch (IOException exception) {
            throw new IllegalStateException("Failed to inspect " + source, exception);
        }
    }
}
