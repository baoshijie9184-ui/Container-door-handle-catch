package com.ruanzhu.doorhandle.module.app.config;

import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;

class SingleEnterpriseSharedDataMigrationContractTest {

    @Test
    void migrationCreatesSharedOperationAuditLogWithoutTenantColumn() throws Exception {
        Path path = Path.of("src", "main", "resources", "db",
                "migration-V15-single-enterprise-shared-data.sql");

        assertThat(path).exists();
        String sql = Files.readString(path, StandardCharsets.UTF_8);
        assertThat(sql)
                .contains("operation_audit_log")
                .contains("idx_audit_operator_time")
                .contains("idx_audit_resource_time")
                .contains("idx_audit_created_at")
                .contains("utf8mb4")
                .doesNotContain("tenant_id");
    }
}
