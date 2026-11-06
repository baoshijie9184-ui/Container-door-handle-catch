package com.ruanzhu.doorhandle.module.app.service;

import com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos;
import com.ruanzhu.doorhandle.module.app.testsupport.CompactWorkflowFixture;
import com.ruanzhu.doorhandle.module.app.testsupport.DualSchemaCopyMySqlFixture;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Set;
import java.util.ArrayList;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ScriptStatementFailedException;
import org.springframework.web.server.ResponseStatusException;
import static org.assertj.core.api.Assertions.*;

/** Original V26 and distinct compact target, admitted ECS MySQL only; both schemas pre-provisioned empty. */
@EnabledIfSystemProperty(named="agent.memory.copy.source-config",matches=".+")
@EnabledIfSystemProperty(named="agent.memory.copy.target-config",matches=".+")
class MemoryGovernanceMigrationMySqlTest {
    private static final LocalDateTime BEIJING=LocalDateTime.of(2026,10,14,16,30);
    private static final LocalDateTime UTC=BEIJING.minusHours(8);
    private final TenantContext owner=new TenantContext(42L,"fixture"),other=new TenantContext(43L,"other");
    private DriverManagerDataSource targetDataSource;
    private JdbcTemplate jdbc,legacy;
    private DualSchemaCopyMySqlFixture fixture;
    private MemoryPreferenceService preferences;
    private String schema;
    private Path sqlRoot;

    @BeforeEach void setup() throws Exception {
        fixture=new DualSchemaCopyMySqlFixture(System.getProperty("agent.memory.copy.source-config"),System.getProperty("agent.memory.copy.target-config"),"doorhandle_wb_verify_",
                Set.of("agent_memory_preference","agent_memory_audit"),Set.of("runtime_state","workflow_instance","scheduled_plan","audit_event"));
        targetDataSource=fixture.targetDataSource();jdbc=fixture.target();legacy=fixture.source();schema=fixture.sourceName();
        sqlRoot=sourceRoot().resolve("sql/mysql");
        CompactWorkflowFixture.install(jdbc);
        fixture.executeSource(Files.readString(sqlRoot.resolve("migration-V26-personal-memory-governance.sql")));
        preferences=new MemoryPreferenceService(jdbc,new DataSourceTransactionManager(targetDataSource));
        legacy.update("INSERT INTO agent_memory_preference VALUES(42,FALSE,TRUE,7,?)",BEIJING);
        legacy.update("INSERT INTO agent_memory_audit(owner_user_id,action_name,outcome,preference_revision,read_enabled,save_enabled,created_at,updated_at) VALUES(42,'PREFERENCE_CHANGED','SUCCEEDED',7,FALSE,TRUE,?,?)",BEIJING,BEIJING.plusMinutes(1));
        for(String[] row:List.of(new String[]{"DELETE","SUCCEEDED","Original_Case","mine"},new String[]{"AUTOSAVE","UNKNOWN","unknown",null},new String[]{"UPDATE","PENDING","pending","mine"}))
            legacy.update("INSERT INTO agent_memory_audit(owner_user_id,action_name,outcome,request_key,memory_id,content_digest,created_at,updated_at) VALUES(42,?,?,?,?,?,?,?)",
                    row[0],row[1],row[2],row[3],"a".repeat(64),BEIJING,BEIJING.plusMinutes(2));
    }

    @AfterEach void cleanup() throws Exception {if(fixture!=null)fixture.close();}

    private static Path sourceRoot(){for(Path path=Path.of("").toAbsolutePath();path!=null;path=path.getParent())if(Files.isRegularFile(path.resolve("sql/mysql/compact/copy/36-memory-governance.sql")))return path;throw new IllegalStateException("Checkout migration sources missing");}
    private void execute(String sql) throws Exception {
        fixture.executeTarget(sql);
    }
    private void migrate() throws Exception {migrate("+08:00");}
    private void migrate(String offset) throws Exception {
        execute(Files.readString(sqlRoot.resolve("compact/copy/36-memory-governance.sql"))
                .replace("__SOURCE_SCHEMA__",schema).replace("__SOURCE_MEMORY_OFFSET__",offset));
    }
    @ParameterizedTest
    @CsvSource({"agent_memory_preference,updated_at,1960-01-02T03:04:05", "agent_memory_preference,updated_at,9999-01-02T03:04:05",
            "agent_memory_audit,created_at,1960-01-02T03:04:05", "agent_memory_audit,created_at,9999-01-02T03:04:05",
            "agent_memory_audit,updated_at,1960-01-02T03:04:05", "agent_memory_audit,updated_at,9999-01-02T03:04:05"})
    void nonConvertedDatesCannotBeImportedAsUtc(String table,String column,String original) {
        var value=LocalDateTime.parse(original);
        legacy.update("UPDATE "+table+" SET "+column+"=?",value);
        assertThatThrownBy(this::migrate).isInstanceOf(ScriptStatementFailedException.class);
        targetEmpty();
        assertThat(legacy.queryForList("SELECT "+column+" FROM "+table,LocalDateTime.class)).allMatch(value::equals);
    }
    @ParameterizedTest @ValueSource(strings={"+00:00","-05:30"})
    void explicitOffsetPreservesBothHistoricalTimes(String offset) throws Exception {
        // V26 records DATETIME(0); sub-second precision is not present in this source.
        var original=LocalDateTime.parse("2026-10-14T16:30:12");
        legacy.update("UPDATE agent_memory_preference SET updated_at=?",original);
        legacy.update("UPDATE agent_memory_audit SET created_at=?,updated_at=?",original,original.plusMinutes(2));
        migrate(offset);
        var expected=original.minusSeconds(java.time.ZoneOffset.of(offset).getTotalSeconds());
        assertThat(jdbc.queryForObject("SELECT updated_at FROM runtime_state WHERE namespace='MEMORY_PREFERENCE'",LocalDateTime.class)).isEqualTo(expected);
        assertThat(jdbc.queryForObject("SELECT created_at FROM workflow_instance WHERE request_id='Original_Case'",LocalDateTime.class)).isEqualTo(expected);
        assertThat(jdbc.queryForObject("SELECT updated_at FROM workflow_instance WHERE request_id='Original_Case'",LocalDateTime.class)).isEqualTo(expected.plusMinutes(2));
        assertThat(jdbc.queryForObject("SELECT finished_at FROM workflow_instance WHERE request_id='Original_Case'",LocalDateTime.class)).isEqualTo(expected.plusMinutes(2));
    }
    @ParameterizedTest @ValueSource(strings={"audit_event","workflow_instance"})
    void unrelatedPublicStateCannotBeInjected(String table) {
        String mutation=table.equals("audit_event")?"NEW.quantity=17,NEW.unit='BYTES'":"NEW.error_code='INJECTED'";
        jdbc.execute("CREATE TRIGGER corrupt_memory_extra BEFORE INSERT ON "+table+" FOR EACH ROW SET "+mutation);
        assertThatThrownBy(this::migrate).isInstanceOf(ScriptStatementFailedException.class);
        targetEmpty();
    }
    private void targetEmpty() {
        for(String table:List.of("runtime_state","workflow_instance","audit_event"))assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM "+table,Long.class)).isZero();
        assertThat(legacy.queryForObject("SELECT COUNT(*) FROM agent_memory_audit",Long.class)).isEqualTo(4);
        assertThat(legacy.queryForObject("SELECT revision FROM agent_memory_preference WHERE owner_user_id=42",Integer.class)).isEqualTo(7);
    }

    @Test void migrationPreservesPreferencesRequestIdentityBothTimesAndUnknownOutcome() throws Exception {
        migrate();
        assertThat(schema).isNotEqualTo(fixture.targetName());
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('agent_memory_audit','agent_memory_preference')",Long.class)).isZero();
        assertThat(preferences.get(owner).readEnabled()).isFalse();assertThat(preferences.get(owner).saveEnabled()).isTrue();assertThat(preferences.get(owner).revision()).isEqualTo(7);
        assertThat(preferences.get(other)).isEqualTo(new MemoryDtos.Preference(true,true,0,null));
        assertThat(preferences.audit(owner)).hasSize(4);assertThat(preferences.audit(other)).isEmpty();
        assertThat(jdbc.queryForObject("SELECT updated_at FROM runtime_state WHERE namespace='MEMORY_PREFERENCE'",LocalDateTime.class)).isEqualTo(UTC);
        assertThat(jdbc.queryForObject("SELECT created_at FROM runtime_state WHERE namespace='MEMORY_PREFERENCE'",LocalDateTime.class)).isNull();
        var original=jdbc.queryForMap("SELECT * FROM workflow_instance WHERE request_id='Original_Case'");
        assertThat(original.get("request_sha256")).isEqualTo("a".repeat(64));
        assertThat(jdbc.queryForObject("SELECT created_at FROM workflow_instance WHERE request_id='Original_Case'",LocalDateTime.class)).isEqualTo(UTC);
        assertThat(jdbc.queryForObject("SELECT updated_at FROM workflow_instance WHERE request_id='Original_Case'",LocalDateTime.class)).isEqualTo(UTC.plusMinutes(2));
        assertThat(jdbc.queryForObject("SELECT finished_at FROM workflow_instance WHERE request_id='unknown'",LocalDateTime.class)).isNull();
        assertThat(preferences.reserveDelete(owner,"mine",new MemoryDtos.Delete("Original_Case","a".repeat(64),true))).isTrue();
        assertThatThrownBy(()->preferences.reserveDelete(owner,"another",new MemoryDtos.Delete("Original_Case","a".repeat(64),true))).hasMessageContaining("409");
        assertThat(preferences.reserveDelete(owner,"mine",new MemoryDtos.Delete("original_case","a".repeat(64),true))).isFalse();
        assertThat(preferences.automaticOutcome(owner,"unknown")).isEqualTo("UNKNOWN");
        assertThatThrownBy(()->preferences.reserveAutomatic(owner,"unknown","a".repeat(64))).hasMessageContaining("409");
        preferences.reconcileAutomatic(owner,"unknown","SUCCEEDED");
        assertThat(preferences.reserveAutomatic(owner,"unknown","a".repeat(64))).isTrue();
        assertThat(jdbc.queryForObject("SELECT outcome FROM audit_event WHERE legacy_source='agent_memory_audit' AND legacy_key='3'",String.class)).isEqualTo("UNKNOWN");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='MEMORY_OPERATION' AND request_id='unknown'",Long.class)).isEqualTo(2);
        assertThat(legacy.queryForObject("SELECT outcome FROM agent_memory_audit WHERE request_key='unknown'",String.class)).isEqualTo("UNKNOWN");
    }

    @ParameterizedTest @ValueSource(strings={"missing-hash","missing-memory","unknown-action","padded-action","padded-outcome","invalid-preference","invalid-time"})
    void incompatibleSourceFactsAbortWithoutGuessingOrDroppingRows(String corruption) {
        switch(corruption) {
            case "missing-hash" -> legacy.update("UPDATE agent_memory_audit SET content_digest=NULL WHERE request_key='unknown'");
            case "missing-memory" -> legacy.update("UPDATE agent_memory_audit SET memory_id=NULL WHERE request_key='Original_Case'");
            case "unknown-action" -> legacy.update("UPDATE agent_memory_audit SET action_name='UNSUPPORTED' WHERE request_key='Original_Case'");
            case "padded-action" -> legacy.update("UPDATE agent_memory_audit SET action_name='DELETE ' WHERE request_key='Original_Case'");
            case "padded-outcome" -> legacy.update("UPDATE agent_memory_audit SET outcome='SUCCEEDED ' WHERE request_key='Original_Case'");
            case "invalid-preference" -> legacy.update("UPDATE agent_memory_preference SET read_enabled=2");
            case "invalid-time" -> {assertThatThrownBy(()->execute(Files.readString(sqlRoot.resolve("compact/copy/36-memory-governance.sql")).replace("__SOURCE_SCHEMA__",schema).replace("__SOURCE_MEMORY_OFFSET__","invalid-offset"))).isInstanceOf(ScriptStatementFailedException.class);targetEmpty();return;}
            default -> throw new IllegalArgumentException(corruption);
        }
        assertThatThrownBy(this::migrate).isInstanceOf(ScriptStatementFailedException.class);targetEmpty();
    }

    @Test void sameSchemaIsRejectedBeforeReadingAnyLegacyTable() {
        assertThatThrownBy(()->execute(Files.readString(sqlRoot.resolve("compact/copy/36-memory-governance.sql"))
                .replace("__SOURCE_SCHEMA__",fixture.targetName()).replace("__SOURCE_MEMORY_OFFSET__","+08:00")))
                .isInstanceOf(ScriptStatementFailedException.class).hasMessageContaining("DATABASE()");
        targetEmpty();
    }

    @ParameterizedTest @ValueSource(strings={"extra-column","type","nullable","collation","default","unique-key","index","check","trigger"})
    void undeclaredSourceMetadataIsNeverSilentlyIgnored(String corruption) {
        switch(corruption) {
            case "extra-column" -> legacy.execute("ALTER TABLE agent_memory_audit ADD extra_memory_fact VARCHAR(64) NULL");
            case "type" -> legacy.execute("ALTER TABLE agent_memory_audit MODIFY request_key VARCHAR(65) NULL");
            case "nullable" -> legacy.execute("ALTER TABLE agent_memory_preference MODIFY read_enabled BOOLEAN NULL DEFAULT TRUE");
            case "collation" -> legacy.execute("ALTER TABLE agent_memory_audit MODIFY request_key VARCHAR(64) COLLATE utf8mb4_unicode_ci NULL");
            case "default" -> legacy.execute("ALTER TABLE agent_memory_preference MODIFY read_enabled BOOLEAN NOT NULL DEFAULT FALSE");
            case "unique-key" -> legacy.execute("ALTER TABLE agent_memory_audit DROP INDEX uk_memory_request");
            case "index" -> legacy.execute("ALTER TABLE agent_memory_audit DROP INDEX idx_memory_audit_owner");
            case "check" -> legacy.execute("ALTER TABLE agent_memory_preference ADD CONSTRAINT new_source_check CHECK(revision>=0)");
            case "trigger" -> legacy.execute("CREATE TRIGGER unknown_source_memory BEFORE INSERT ON agent_memory_audit FOR EACH ROW SET NEW.outcome=NEW.outcome");
            default -> throw new IllegalArgumentException(corruption);
        }
        assertThatThrownBy(this::migrate).isInstanceOf(ScriptStatementFailedException.class);targetEmpty();
    }

    @ParameterizedTest @ValueSource(strings={"fingerprint","missing-original-time","workflow-source-space","workflow-key-space","audit-source-space","audit-key-space"})
    void equalCountsCannotHideChangedOrMissingOriginalFacts(String corruption) {
        if("fingerprint".equals(corruption))jdbc.execute("CREATE TRIGGER corrupt_memory_copy BEFORE INSERT ON workflow_instance FOR EACH ROW SET NEW.request_sha256=REPEAT('f',64)");
        else if("missing-original-time".equals(corruption))jdbc.execute("CREATE TRIGGER corrupt_memory_copy BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.payload_json=JSON_REMOVE(NEW.payload_json,'$.legacyUpdatedAt')");
        else if("workflow-source-space".equals(corruption))jdbc.execute("CREATE TRIGGER corrupt_memory_copy BEFORE INSERT ON workflow_instance FOR EACH ROW SET NEW.legacy_source=CONCAT(NEW.legacy_source,' ')");
        else if("workflow-key-space".equals(corruption))jdbc.execute("CREATE TRIGGER corrupt_memory_copy BEFORE INSERT ON workflow_instance FOR EACH ROW SET NEW.legacy_key=CONCAT(NEW.legacy_key,' ')");
        else if("audit-source-space".equals(corruption))jdbc.execute("CREATE TRIGGER corrupt_memory_copy BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.legacy_source=CONCAT(NEW.legacy_source,' ')");
        else jdbc.execute("CREATE TRIGGER corrupt_memory_copy BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.legacy_key=CONCAT(NEW.legacy_key,' ')");
        var failure=assertThatThrownBy(this::migrate).isInstanceOf(ScriptStatementFailedException.class);
        if(corruption.endsWith("-space"))failure.hasMessageContaining(corruption.startsWith("workflow-")?"LEFT JOIN workflow_instance":"LEFT JOIN audit_event");
        targetEmpty();
    }

    @Test void preferenceAndMutationTransitionsRollBackWhenTheirImmutableAuditFails() throws Exception {
        migrate();
        jdbc.execute("ALTER TABLE audit_event ADD CONSTRAINT reject_new_memory_event CHECK((kind='MEMORY_PREFERENCE' AND revision<=7) OR (kind='MEMORY_OPERATION' AND revision=0))");
        assertThatThrownBy(()->preferences.change(owner,new MemoryDtos.ChangePreference(7,true,false))).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(preferences.get(owner).revision()).isEqualTo(7);assertThat(preferences.get(owner).readEnabled()).isFalse();
        assertThatThrownBy(()->preferences.reconcileAutomatic(owner,"unknown","SUCCEEDED")).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(preferences.automaticOutcome(owner,"unknown")).isEqualTo("UNKNOWN");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event",Long.class)).isEqualTo(4);
    }

    @Test void concurrentRequestsDispatchOnceAcrossServiceInstances() throws Exception {
        migrate();var start=new CountDownLatch(1);var dispatches=new AtomicInteger();var conflicts=new AtomicInteger();var workers=Executors.newFixedThreadPool(4);
        try {
            var futures=new ArrayList<Future<?>>();
            for(int index=0;index<4;index++)futures.add(workers.submit(()->{
                try {start.await();var service=new MemoryPreferenceService(new JdbcTemplate(targetDataSource),new DataSourceTransactionManager(targetDataSource));
                    if(!service.reserveAutomatic(owner,"concurrent","b".repeat(64)))dispatches.incrementAndGet();
                } catch(ResponseStatusException expected){assertThat(expected.getStatusCode().value()).isEqualTo(409);conflicts.incrementAndGet();}
                catch(InterruptedException error){Thread.currentThread().interrupt();throw new IllegalStateException(error);}
            }));
            start.countDown();for(var future:futures)future.get(15,TimeUnit.SECONDS);
            assertThat(dispatches).hasValue(1);assertThat(conflicts).hasValue(3);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE request_id='concurrent'",Long.class)).isEqualTo(1);
        } finally {workers.shutdownNow();}
    }

    @Test void populatedTargetCannotBeOverwrittenByRerunningTheCopy() throws Exception {
        migrate();assertThatThrownBy(this::migrate).isInstanceOf(ScriptStatementFailedException.class);
        assertThat(preferences.audit(owner)).hasSize(4);assertThat(preferences.get(owner).revision()).isEqualTo(7);
    }
}
