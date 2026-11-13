package com.ruanzhu.doorhandle.module.ai.persistence;

import com.ruanzhu.doorhandle.module.ai.EcsIsolatedMysql;
import com.ruanzhu.doorhandle.framework.persistence.JdbcOwnerLock;
import javax.sql.DataSource;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.dao.InvalidDataAccessResourceUsageException;
import static org.assertj.core.api.Assertions.*;
import static com.ruanzhu.doorhandle.module.ai.EcsIsolatedMysql.assertCheckViolation;

/** Executes the same concurrency contracts on MySQL 8.4 after the existing ECS fixture guard. */
@EnabledIfSystemProperty(named = "agent.journal.mysql", matches = "true")
class JdbcOwnerLockMySqlTest extends JdbcOwnerLockTest {
    @Override protected DataSource dataSource() throws Exception {
        return EcsIsolatedMysql.pool(System.getProperty("agent.journal.mysql-file"),
                "doorhandle_agent_verify_", "ecsit_", 4);
    }

    @Test void persistedCoordinationStateEnforcesCounterRevisionAndObjectSettings() {
        assertCheckViolation(() -> jdbc.update("INSERT INTO runtime_state(namespace,owner_id,revision) VALUES('WORKSPACE',?,-1)", owner), "ck_runtime_revision");
        assertCheckViolation(() -> jdbc.update("INSERT INTO runtime_state(namespace,owner_id,counter_value) VALUES('WORKSPACE',?,-1)", owner), "ck_runtime_counter");
        assertCheckViolation(() -> jdbc.update("INSERT INTO runtime_state(namespace,owner_id,payload_json) VALUES('WORKSPACE',?,'[]')", owner), "ck_runtime_payload");
        jdbc.update("INSERT INTO runtime_state(namespace,owner_id,payload_json) VALUES('WORKSPACE',?,'{}')", owner);
        assertThat(jdbc.queryForObject("SELECT JSON_TYPE(payload_json) FROM runtime_state WHERE namespace='WORKSPACE' AND owner_id=? AND scope_key=''", String.class, owner))
                .isEqualTo("OBJECT");
    }

    @Test void preflightRejectsWrongEnginePrimaryKeyAndCaseInsensitiveNamespace() {
        // Preserve the full production-DDL fixture: its SDK index exceeds MyISAM's 1000-byte key limit.
        jdbc.execute("RENAME TABLE runtime_state TO runtime_state_owner_lock_schema_backup");
        try {
            assertInvalidCoordinationSchema("MyISAM", "namespace,owner_id,scope_key", "utf8mb4_bin", "InnoDB");
            assertInvalidCoordinationSchema("InnoDB", "owner_id,namespace,scope_key", "utf8mb4_bin", "primary key");
            assertInvalidCoordinationSchema("InnoDB", "namespace,owner_id,scope_key", "utf8mb4_unicode_ci", "collation");
        } finally {
            jdbc.execute("DROP TABLE IF EXISTS runtime_state");
            jdbc.execute("RENAME TABLE runtime_state_owner_lock_schema_backup TO runtime_state");
        }
        JdbcOwnerLock.validateSchema(jdbc);
    }

    private void assertInvalidCoordinationSchema(String engine, String primaryKey, String namespaceCollation,
            String expectedFailure) {
        // Keep every validated column type, width and nullability; vary only the requested metadata defect.
        jdbc.execute("""
                CREATE TABLE runtime_state (
                    namespace VARCHAR(64) COLLATE %s NOT NULL,
                    owner_id BIGINT NOT NULL,
                    scope_key VARCHAR(160) COLLATE utf8mb4_bin NOT NULL DEFAULT '',
                    revision BIGINT NOT NULL DEFAULT 0,
                    created_at DATETIME(6) NULL,
                    PRIMARY KEY (%s)
                ) ENGINE=%s DEFAULT CHARSET=utf8mb4
                """.formatted(namespaceCollation, primaryKey, engine));
        try {
            assertThatThrownBy(() -> JdbcOwnerLock.validateSchema(jdbc))
                    .isInstanceOf(InvalidDataAccessResourceUsageException.class)
                    .hasMessageContaining(expectedFailure);
        } finally {
            jdbc.execute("DROP TABLE runtime_state");
        }
    }
}
