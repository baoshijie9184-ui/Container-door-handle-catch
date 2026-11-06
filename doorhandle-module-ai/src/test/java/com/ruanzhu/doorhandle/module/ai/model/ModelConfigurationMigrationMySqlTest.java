package com.ruanzhu.doorhandle.module.ai.model;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.ai.EcsIsolatedMysql;
import com.ruanzhu.doorhandle.module.ai.testsupport.CompactModelConfigurationFixture;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.support.EncodedResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.jdbc.datasource.init.ScriptUtils;
import org.springframework.transaction.support.TransactionTemplate;
import static org.assertj.core.api.Assertions.*;

/** Historical V41 and the real compact copy script; execution is restricted to an admitted ECS fixture. */
@EnabledIfSystemProperty(named="agent.model-config.mysql-file",matches=".+")
class ModelConfigurationMigrationMySqlTest {
    DriverManagerDataSource source;
    JdbcTemplate jdbc;
    ModelConfigurationStore store;
    final ModelConfigCipher cipher=new ModelConfigCipher(new byte[32]);
    final LocalDateTime beijing=LocalDateTime.of(2026,10,14,16,30,12,123456000),utc=beijing.minusHours(8);
    final String fingerprint="b".repeat(64);
    String snapshot,envelope;

    @BeforeEach void setup() throws Exception {
        source=EcsIsolatedMysql.open(System.getProperty("agent.model-config.mysql-file"),"doorhandle_model_verify_");
        jdbc=new JdbcTemplate(source);
        CompactModelConfigurationFixture.install(jdbc);
        var legacy=new ResourceDatabasePopulator(new FileSystemResource("../sql/mysql/migration-V41-model-configuration.sql"));
        legacy.setSqlScriptEncoding("UTF-8");legacy.execute(source);
        snapshot=cipher.seal("model-config",11,"{\"fixture\":\"配置密文原文\"}");
        envelope=cipher.seal("mem0-llm",11,"{\"fixture\":\"记忆连接密文原文\"}");
        jdbc.update("""
                INSERT INTO agent_model_configuration(revision,base_revision,status,document_json,sealed_snapshot,
                    memory_envelope,creator_user_id,request_id,request_sha256,memory_state,created_at,published_at)
                VALUES(11,0,'PUBLISHED','{}',?,?,NULL,'bootstrap',?,'ENVIRONMENT',?,?)
                """,snapshot,envelope,"a".repeat(64),beijing,beijing);
        jdbc.update("""
                INSERT INTO agent_model_configuration(revision,base_revision,status,document_json,sealed_snapshot,
                    memory_envelope,creator_user_id,request_id,request_sha256,memory_state,created_at)
                VALUES(12,11,'VALIDATED','{}',?,?,3,'Draft_Case_Sensitive',?,'PENDING',?)
                """,cipher.seal("model-config",12,"{}"),cipher.seal("mem0-llm",12,"{}"),"c".repeat(64),beijing.plusMinutes(1));
        jdbc.update("UPDATE agent_model_config_control SET active_revision=11,sequence_value=12 WHERE control_id=1");
        jdbc.update("""
                INSERT INTO agent_model_revoked_key(provider,key_sha256,actor_user_id,request_id,memory_propagated,created_at)
                VALUES('dashscope',?,3,'撤销请求',FALSE,?)
                """,fingerprint,beijing);
        jdbc.update("""
                INSERT INTO agent_model_config_command(actor_user_id,request_id,action,target,revision,created_at)
                VALUES(3,'Validate_Case_Sensitive','VALIDATE','12',12,?)
                """,beijing.plusMinutes(2));
        for(String status:new String[]{"PASSED","FAILED","STARTED"})
            jdbc.update("INSERT INTO agent_model_json_probe(revision,model_id,request_id,status,created_at) VALUES(12,'dashscope:中文模型',?,?,?)",
                    "probe-"+status,status,beijing.plusMinutes(1));
        store=new ModelConfigurationStore(jdbc,new ObjectMapper());
    }

    void migrate() throws Exception {
        String schema=jdbc.queryForObject("SELECT DATABASE()",String.class);
        if(schema==null||!schema.matches("doorhandle_model_verify_[a-f0-9]{10}"))
            throw new SecurityException("Copy fixture is outside the admitted disposable schema");
        String sql=Files.readString(Path.of("../sql/mysql/compact/copy/26-model-configuration.sql"))
                .replace("__SOURCE_SCHEMA__",schema).replace("__SOURCE_MODEL_OFFSET__","+08:00");
        try(var connection=source.getConnection()) {
            connection.setAutoCommit(false);
            try {
                ScriptUtils.executeSqlScript(connection,new EncodedResource(
                        new ByteArrayResource(sql.getBytes(StandardCharsets.UTF_8)),StandardCharsets.UTF_8));
            } catch(Exception failure) {connection.rollback();throw failure;}
        }
    }

    void assertTargetEmptyAndSourcePreserved() {
        for(String table:new String[]{"llm_configuration","runtime_state","workflow_instance"})
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM "+table,Long.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_model_configuration",Long.class)).isEqualTo(2);
        assertThat(jdbc.queryForObject("SELECT sealed_snapshot FROM agent_model_configuration WHERE revision=11",String.class)).isEqualTo(snapshot);
    }

    @Test void migrationPreservesCiphertextIdentityRevocationAndUnknownProbeFacts() throws Exception {
        migrate();
        assertThat(jdbc.queryForObject("SELECT sealed_snapshot FROM llm_configuration WHERE revision=11",String.class)).isEqualTo(snapshot);
        assertThat(jdbc.queryForObject("SELECT memory_envelope FROM llm_configuration WHERE revision=11",String.class)).isEqualTo(envelope);
        assertThat(cipher.open("model-config",11,snapshot)).contains("配置密文原文");
        assertThatThrownBy(()->cipher.open("model-config",12,snapshot)).isInstanceOf(IllegalStateException.class);
        assertThat(store.activeRevision()).isEqualTo(11);
        var control=new TransactionTemplate(new DataSourceTransactionManager(source)).execute(status->store.lockControl());
        assertThat(control).containsEntry("sequence_value",12L);
        assertThat(store.revoked("dashscope",fingerprint)).isTrue();
        assertThat(store.pendingRevocations()).hasSize(1);
        assertThat(store.receipt(3,"Validate_Case_Sensitive","VALIDATE","12")).isEqualTo(12L);
        assertThat(store.receipt(3,"validate_case_sensitive","VALIDATE","12")).isNull();
        assertThatThrownBy(()->store.receipt(3,"Validate_Case_Sensitive","PUBLISH","12")).hasMessageContaining("请求编号");
        assertThat(store.hasPassedProbe(12,"dashscope:中文模型")).isTrue();
        assertThat(store.hasPassedProbe(12,"dashscope:其他模型")).isFalse();
        for(String state:new String[]{"PASSED","FAILED","STARTED"}) {
            var probe=store.probe(12,"probe-"+state).orElseThrow();
            assertThat(probe.status()).isEqualTo(state);
            assertThat(probe.ownerUserId()).isEqualTo(3);
            assertThat(probe.actorUserId()).isNull();
            assertThat(probe.finishedAt()).isNull();
            assertThat(probe.createdAt()).isEqualTo(utc.plusMinutes(1));
            assertThat(probe.requestSha256()).isEqualTo(ModelConfigurationStore.digest("12","dashscope:中文模型"));
        }
        assertThat(jdbc.queryForObject("SELECT created_at FROM runtime_state WHERE namespace='MODEL_CONFIG_CONTROL'",LocalDateTime.class)).isNull();
        assertThat(jdbc.queryForObject("SELECT created_at FROM llm_configuration WHERE revision=11",LocalDateTime.class)).isEqualTo(utc);
    }

    @ParameterizedTest @ValueSource(strings={"missing-control","low-counter","second-published","unknown-probe-owner","orphan-command","orphan-probe","invalid-propagation","unknown-status"})
    void inconsistentHistoryAbortsWithoutGuessingOwnershipOrResettingVersions(String corruption) {
        switch(corruption) {
            case "missing-control"->jdbc.update("DELETE FROM agent_model_config_control");
            case "low-counter"->jdbc.update("UPDATE agent_model_config_control SET sequence_value=10");
            case "second-published"->jdbc.update("UPDATE agent_model_configuration SET status='PUBLISHED' WHERE revision=12");
            case "unknown-probe-owner"->jdbc.update("UPDATE agent_model_configuration SET creator_user_id=NULL WHERE revision=12");
            case "orphan-command"->jdbc.update("UPDATE agent_model_config_command SET revision=99");
            case "orphan-probe"->jdbc.update("UPDATE agent_model_json_probe SET revision=99");
            case "invalid-propagation"->jdbc.update("UPDATE agent_model_revoked_key SET memory_propagated=2");
            case "unknown-status"->jdbc.update("UPDATE agent_model_json_probe SET status='UNKNOWN'");
            default->throw new IllegalArgumentException(corruption);
        }
        assertThatThrownBy(this::migrate).isInstanceOf(org.springframework.jdbc.datasource.init.ScriptStatementFailedException.class);
        assertTargetEmptyAndSourcePreserved();
    }

    @ParameterizedTest @ValueSource(strings={"ciphertext","request-key","command-key-space","probe-key-space","scope-space","legacy-key-space"})
    void finalReconciliationRejectsEqualCountsWithChangedContent(String corruption) {
        if("ciphertext".equals(corruption))
            jdbc.execute("CREATE TRIGGER corrupt_model_copy BEFORE INSERT ON llm_configuration FOR EACH ROW SET NEW.sealed_snapshot=CONCAT(NEW.sealed_snapshot,'changed')");
        else {
            String assignment=switch(corruption) {
                case "request-key"->"NEW.request_id=IF(NEW.kind='MODEL_CONFIG_COMMAND','Changed_Key',NEW.request_id)";
                case "command-key-space"->"NEW.request_id=IF(NEW.kind='MODEL_CONFIG_COMMAND',CONCAT(NEW.request_id,' '),NEW.request_id)";
                case "probe-key-space"->"NEW.request_id=IF(NEW.kind='MODEL_JSON_PROBE',CONCAT(NEW.request_id,' '),NEW.request_id)";
                case "scope-space"->"NEW.idempotency_scope=CONCAT(NEW.idempotency_scope,' ')";
                case "legacy-key-space"->"NEW.legacy_key=CONCAT(NEW.legacy_key,' ')";
                default->throw new IllegalArgumentException(corruption);
            };
            jdbc.execute("CREATE TRIGGER corrupt_model_copy BEFORE INSERT ON workflow_instance FOR EACH ROW SET "+assignment);
        }
        assertThatThrownBy(this::migrate).isInstanceOf(org.springframework.jdbc.datasource.init.ScriptStatementFailedException.class);
        assertTargetEmptyAndSourcePreserved();
    }

    @Test void lateConstraintFailureRollsBackSnapshotsAndProtectedRuntimeRows() {
        jdbc.execute("ALTER TABLE workflow_instance ADD CONSTRAINT reject_model_copy CHECK(kind<>'MODEL_JSON_PROBE')");
        assertThatThrownBy(this::migrate).isInstanceOf(org.springframework.jdbc.datasource.init.ScriptStatementFailedException.class);
        assertTargetEmptyAndSourcePreserved();
    }

    @Test void repeatedMigrationCannotOverwriteAnAlreadyPopulatedTarget() throws Exception {
        migrate();
        assertThatThrownBy(this::migrate).isInstanceOf(org.springframework.jdbc.datasource.init.ScriptStatementFailedException.class);
        assertThat(store.activeRevision()).isEqualTo(11);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_configuration",Long.class)).isEqualTo(2);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance",Long.class)).isEqualTo(4);
        assertThat(store.revoked("dashscope",fingerprint)).isTrue();
    }
}
