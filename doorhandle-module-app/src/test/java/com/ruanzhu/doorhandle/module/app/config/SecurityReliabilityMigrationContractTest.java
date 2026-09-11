package com.ruanzhu.doorhandle.module.app.config;

import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;

class SecurityReliabilityMigrationContractTest {

    @Test
    void migrationAddsSecurityAndIdempotencyColumns() throws Exception {
        Path path = Path.of("src", "main", "resources", "db",
                "migration-V14-security-reliability-hardening.sql");

        assertThat(path).exists();
        String sql = Files.readString(path, StandardCharsets.UTF_8);
        assertThat(sql)
                .contains("`role`")
                .contains("`dispatch_id`")
                .contains("`last_finished_event_id`")
                .contains("`error_message`")
                .containsIgnoringCase("LOWER(username) = 'admin'")
                .contains("'OPERATOR'");
    }
}
