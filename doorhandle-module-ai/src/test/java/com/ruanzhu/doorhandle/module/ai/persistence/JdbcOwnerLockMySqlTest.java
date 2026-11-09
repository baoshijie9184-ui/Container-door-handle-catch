package com.ruanzhu.doorhandle.module.ai.persistence;

import com.ruanzhu.doorhandle.module.ai.EcsIsolatedMysql;
import com.ruanzhu.doorhandle.framework.persistence.JdbcOwnerLock;
import javax.sql.DataSource;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
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
        try {
            jdbc.execute("ALTER TABLE runtime_state ENGINE=MyISAM");
            assertThatThrownBy(() -> JdbcOwnerLock.validateSchema(jdbc)).hasMessageContaining("InnoDB");
        } finally {
            jdbc.execute("ALTER TABLE runtime_state ENGINE=InnoDB");
        }
        try {
            jdbc.execute("ALTER TABLE runtime_state DROP PRIMARY KEY, ADD PRIMARY KEY(owner_id,namespace,scope_key)");
            assertThatThrownBy(() -> JdbcOwnerLock.validateSchema(jdbc)).hasMessageContaining("primary key");
        } finally {
            jdbc.execute("ALTER TABLE runtime_state DROP PRIMARY KEY, ADD PRIMARY KEY(namespace,owner_id,scope_key)");
        }
        try {
            jdbc.execute("ALTER TABLE runtime_state MODIFY namespace VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL");
            assertThatThrownBy(() -> JdbcOwnerLock.validateSchema(jdbc)).hasMessageContaining("collation");
        } finally {
            jdbc.execute("ALTER TABLE runtime_state MODIFY namespace VARCHAR(64) COLLATE utf8mb4_bin NOT NULL");
        }
        JdbcOwnerLock.validateSchema(jdbc);
    }
}
