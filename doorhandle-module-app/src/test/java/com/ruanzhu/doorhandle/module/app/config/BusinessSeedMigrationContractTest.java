package com.ruanzhu.doorhandle.module.app.config;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class BusinessSeedMigrationContractTest {

    @Test
    void modelDescriptionNormalizationUsesTheSchemaColumnName() throws IOException {
        String migration = Files.readString(
                Path.of("src", "main", "resources", "db",
                        "migration-V13-business-seed-data-normalization.sql"),
                StandardCharsets.UTF_8);

        assertTrue(migration.contains("`update_description`"));
        assertFalse(migration.contains("`description`"));
    }
}
