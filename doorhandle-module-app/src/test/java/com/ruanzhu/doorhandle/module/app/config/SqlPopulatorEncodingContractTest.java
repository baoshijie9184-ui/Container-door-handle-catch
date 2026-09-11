package com.ruanzhu.doorhandle.module.app.config;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class SqlPopulatorEncodingContractTest {

    private static final String UTF8_CONFIGURATION =
            "populator.setSqlScriptEncoding(StandardCharsets.UTF_8.name());";
    private static final Path SOURCE_DIRECTORY = Path.of("src", "main", "java");
    private static final Path CONFIG_DIRECTORY = SOURCE_DIRECTORY.resolve(
            Path.of("com", "ruanzhu", "doorhandle", "module", "app", "config"));

    @Test
    void businessSeedConfigurationIsTheOnlyCustomSqlPopulator() throws IOException {
        List<String> customPopulators;
        try (var files = Files.walk(SOURCE_DIRECTORY)) {
            customPopulators = files
                    .filter(path -> path.getFileName().toString().endsWith(".java"))
                    .filter(this::containsSqlPopulator)
                    .map(path -> path.getFileName().toString())
                    .sorted()
                    .toList();
        }

        assertThat(customPopulators).containsExactly("BusinessSeedDataConfig.java");
    }

    @Test
    void businessSeedSqlPopulatorExplicitlyReadsSqlAsUtf8() throws IOException {
        Path source = CONFIG_DIRECTORY.resolve("BusinessSeedDataConfig.java");
        String content = Files.readString(source, StandardCharsets.UTF_8);

        assertThat(content)
                .contains("import java.nio.charset.StandardCharsets;")
                .contains(UTF8_CONFIGURATION);
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
