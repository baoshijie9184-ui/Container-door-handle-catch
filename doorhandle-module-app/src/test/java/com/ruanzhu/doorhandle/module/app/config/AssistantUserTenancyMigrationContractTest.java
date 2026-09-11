package com.ruanzhu.doorhandle.module.app.config;

import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;

class AssistantUserTenancyMigrationContractTest {
    @Test
    void migrationBackfillsAndConstrainsAssistantUserIds() throws Exception {
        Path path = Path.of("src/main/resources/db/migration-V16-assistant-user-tenancy.sql");
        assertThat(path).exists();
        String sql = Files.readString(path, StandardCharsets.UTF_8);
        assertThat(sql)
                .contains("chat_project", "chat_session", "user_id")
                .contains("JOIN `users`")
                .contains("idx_chat_session_tenant_status_updated")
                .contains("idx_chat_project_tenant_sort_created")
                .contains("SIGNAL SQLSTATE '45000'")
                .doesNotContain("DROP COLUMN `username`");
    }
}
