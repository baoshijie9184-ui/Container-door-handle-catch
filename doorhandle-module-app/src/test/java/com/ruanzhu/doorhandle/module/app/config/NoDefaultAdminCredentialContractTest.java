package com.ruanzhu.doorhandle.module.app.config;

import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;

class NoDefaultAdminCredentialContractTest {
    @Test
    void schemaDoesNotSeedAWellKnownAdministratorCredential() throws Exception {
        String sql = Files.readString(Path.of("src/main/resources/db/schema.sql"), StandardCharsets.UTF_8);
        assertThat(sql)
                .doesNotContain("1JubAveAPOmdM2wuxLsHAOGDkXOcAaUff2fraVjbpGcvz/.mrQdf6")
                .doesNotContain("INSERT IGNORE INTO users");
    }
}
