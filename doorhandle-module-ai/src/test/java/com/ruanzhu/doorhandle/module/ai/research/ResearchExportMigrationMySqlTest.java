package com.ruanzhu.doorhandle.module.ai.research;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.module.ai.testsupport.CompactAgentJournalFixture;
import com.ruanzhu.doorhandle.module.ai.testsupport.DualSchemaCopyMySqlFixture;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Set;
import java.util.concurrent.*;
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
import org.springframework.transaction.support.TransactionTemplate;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Actual V16/V33/V35 source and distinct compact target; both ECS disposable schemas must be pre-provisioned empty. */
@EnabledIfSystemProperty(named="agent.research.copy.source-config",matches=".+")
@EnabledIfSystemProperty(named="agent.research.copy.target-config",matches=".+")
class ResearchExportMigrationMySqlTest {
    private static final String RUN="11111111-1111-4111-8111-111111111111";
    private static final String EXPORT="22222222-2222-4222-8222-222222222222";
    private static final LocalDateTime BEIJING=LocalDateTime.of(2026,10,14,16,30,12,123456000),UTC=BEIJING.minusHours(8);
    private final AgentActor actor=new AgentActor(1,"fixture",AgentActor.Role.INSPECTOR);
    private DriverManagerDataSource targetDataSource;
    private JdbcTemplate jdbc,legacy;
    private DualSchemaCopyMySqlFixture fixture;
    private DataSourceTransactionManager manager;
    private Path sqlRoot;
    private String schema;

    @BeforeEach void setup() throws Exception {
        fixture=new DualSchemaCopyMySqlFixture(System.getProperty("agent.research.copy.source-config"),System.getProperty("agent.research.copy.target-config"),"doorhandle_agent_verify_",
                Set.of("agent_run","agent_run_event","agent_research_export_audit","agent_research_export_limit"),
                Set.of("runtime_state","workflow_instance","scheduled_plan","audit_event","agent_run"));
        targetDataSource=fixture.targetDataSource();jdbc=fixture.target();legacy=fixture.source();manager=new DataSourceTransactionManager(targetDataSource);
        schema=fixture.sourceName();
        sqlRoot=sourceRoot().resolve("sql/mysql");
        CompactAgentJournalFixture.install(jdbc);
        fixture.executeSource(Files.readString(sqlRoot.resolve("migration-V16-agentscope-run-journal.sql")));
        fixture.executeSource(Files.readString(sqlRoot.resolve("migration-V33-agent-research-export.sql")));
        fixture.executeSource(Files.readString(sqlRoot.resolve("migration-V35-agent-research-export-limit.sql")));
        for(JdbcTemplate runDatabase:List.of(legacy,jdbc))runDatabase.update("""
                INSERT INTO agent_run(run_id,user_id,session_id,main_agent,entry_point,request_key,status,default_model,
                    policy_version,instance_id,started_at,heartbeat_at,lease_expires_at)
                VALUES(?,1,'fixture-session','employee-main','CHAT','original-request','COMPLETED','fixture','v1','fixture',?,?,?)
                """,RUN,UTC,UTC,UTC.plusMinutes(5));
        legacy.update("INSERT INTO agent_research_export_audit(export_id,user_id,run_id,format_version,source_count,expired_source_count,payload_bytes,payload_sha256,created_at) VALUES(?,1,?,1,2,3,513,?,?)",EXPORT,RUN,"a".repeat(64),BEIJING);
        legacy.update("INSERT INTO agent_research_export_limit(user_id,window_ends_at,export_count) VALUES(1,?,2)",BEIJING.plusSeconds(60));
    }

    @AfterEach void cleanup() throws Exception {if(fixture!=null)fixture.close();}

    private static Path sourceRoot(){for(Path path=Path.of("").toAbsolutePath();path!=null;path=path.getParent())if(Files.isRegularFile(path.resolve("sql/mysql/compact/copy/35-research-export.sql")))return path;throw new IllegalStateException("Checkout migration sources missing");}
    private void execute(String sql) throws Exception {
        fixture.executeTarget(sql);
    }
    private void migrate() throws Exception {migrate("+08:00");}
    private void migrate(String offset) throws Exception {
        execute(Files.readString(sqlRoot.resolve("compact/copy/35-research-export.sql"))
                .replace("__SOURCE_SCHEMA__",schema).replace("__SOURCE_EXPORT_OFFSET__",offset));
    }
    @ParameterizedTest
    @CsvSource({"agent_research_export_audit,created_at,1960-01-02T03:04:05.123456", "agent_research_export_audit,created_at,9999-01-02T03:04:05.123456",
            "agent_research_export_limit,window_ends_at,1960-01-02T03:04:05.123456", "agent_research_export_limit,window_ends_at,9999-01-02T03:04:05.123456"})
    void unchangedOutOfRangeDatesDoNotBecomeUtc(String table,String column,String original) {
        var value=LocalDateTime.parse(original);
        legacy.update("UPDATE "+table+" SET "+column+"=?",value);
        assertThatThrownBy(this::migrate).isInstanceOf(ScriptStatementFailedException.class);
        targetEmpty();
        assertThat(legacy.queryForObject("SELECT "+column+" FROM "+table,LocalDateTime.class)).isEqualTo(value);
    }
    @ParameterizedTest @ValueSource(strings={"+00:00","-05:30"})
    void explicitOffsetKeepsReceiptAndWindowMicroseconds(String offset) throws Exception {
        migrate(offset);
        var expected=BEIJING.minusSeconds(java.time.ZoneOffset.of(offset).getTotalSeconds());
        assertThat(jdbc.queryForObject("SELECT occurred_at FROM audit_event WHERE kind='RESEARCH_EXPORT'",LocalDateTime.class)).isEqualTo(expected);
        assertThat(jdbc.queryForObject("SELECT window_ends_at FROM runtime_state WHERE namespace='RESEARCH_EXPORT_LIMIT'",LocalDateTime.class)).isEqualTo(expected.plusSeconds(60));
    }
    @ParameterizedTest @ValueSource(strings={"audit_event","runtime_state"})
    void unrelatedPublicFieldsAbortTheEntireCopy(String table) {
        String mutation=table.equals("audit_event")?"NEW.previous_sha256=REPEAT('a',64)":"NEW.payload_version=2";
        jdbc.execute("CREATE TRIGGER corrupt_export_extra BEFORE INSERT ON "+table+" FOR EACH ROW SET "+mutation);
        assertThatThrownBy(this::migrate).isInstanceOf(ScriptStatementFailedException.class);
        targetEmpty();
    }
    private void targetEmpty() {
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='RESEARCH_EXPORT'",Long.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM runtime_state WHERE namespace='RESEARCH_EXPORT_LIMIT'",Long.class)).isZero();
        assertThat(legacy.queryForObject("SELECT COUNT(*) FROM agent_research_export_audit",Long.class)).isEqualTo(1);
        assertThat(legacy.queryForObject("SELECT payload_sha256 FROM agent_research_export_audit",String.class)).isEqualTo("a".repeat(64));
    }
    private ResearchEvidenceExportService exports() {
        var properties=new ResearchEvidenceProperties();properties.setExportMaxPerWindow(1);
        var research=mock(ResearchEvidenceService.class);
        when(research.view(actor,RUN)).thenReturn(new ResearchEvidenceDtos.View(RUN,true,List.of(),List.of(),null,false,0,3,true));
        return new ResearchEvidenceExportService(research,jdbc,manager,new ObjectMapper(),new ResearchExportRateLimit(jdbc,properties));
    }

    @Test void copyPreservesMetadataWindowTimesAndRunDeletionRestriction() throws Exception {
        migrate();
        var event=jdbc.queryForMap("SELECT * FROM audit_event WHERE kind='RESEARCH_EXPORT'");
        assertThat(event).containsEntry("owner_user_id",1L).containsEntry("resource_id",EXPORT).containsEntry("request_id",EXPORT)
                .containsEntry("run_id",RUN).containsEntry("research_export_run_id",RUN).containsEntry("content_sha256","a".repeat(64)).containsEntry("quantity",513L);
        var payload=new ObjectMapper().readTree((String)event.get("payload_json"));
        assertThat(payload.size()).isEqualTo(3);assertThat(payload.path("sourceCount").asInt()).isEqualTo(2);assertThat(payload.path("expiredSourceCount").asInt()).isEqualTo(3);
        assertThat(jdbc.queryForObject("SELECT occurred_at FROM audit_event WHERE kind='RESEARCH_EXPORT'",LocalDateTime.class)).isEqualTo(UTC);
        assertThat(jdbc.queryForObject("SELECT window_ends_at FROM runtime_state WHERE namespace='RESEARCH_EXPORT_LIMIT'",LocalDateTime.class)).isEqualTo(UTC.plusSeconds(60));
        assertThat(jdbc.queryForMap("SELECT counter_value,created_at,updated_at FROM runtime_state WHERE namespace='RESEARCH_EXPORT_LIMIT'"))
                .containsEntry("counter_value",2L).containsEntry("created_at",null).containsEntry("updated_at",null);
        assertThat(schema).isNotEqualTo(fixture.targetName());
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='agent_research_export_audit'",Long.class)).isZero();
        // Source receipt remains in another schema; only the compact FK can protect this target run.
        assertThatThrownBy(()->jdbc.update("DELETE FROM agent_run WHERE run_id=?",RUN)).isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThatThrownBy(()->jdbc.update("UPDATE audit_event SET owner_user_id=2,actor_user_id=2 WHERE kind='RESEARCH_EXPORT'"))
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
    }

    @ParameterizedTest @ValueSource(strings={"foreign-owner","negative-count","negative-window-count","invalid-version"})
    void sourceFactsCannotBeSilentlyReassignedOrReset(String corruption) {
        switch(corruption) {
            case "foreign-owner" -> legacy.update("UPDATE agent_research_export_audit SET user_id=2");
            case "negative-count" -> legacy.update("UPDATE agent_research_export_audit SET source_count=-1");
            case "negative-window-count" -> legacy.update("UPDATE agent_research_export_limit SET export_count=-1");
            case "invalid-version" -> legacy.update("UPDATE agent_research_export_audit SET format_version=0");
            default -> throw new IllegalArgumentException(corruption);
        }
        assertThatThrownBy(this::migrate).isInstanceOf(ScriptStatementFailedException.class);targetEmpty();
    }

    @Test void sameSchemaIsRejectedBeforeReadingAnyLegacyTable() {
        assertThatThrownBy(()->execute(Files.readString(sqlRoot.resolve("compact/copy/35-research-export.sql"))
                .replace("__SOURCE_SCHEMA__",fixture.targetName()).replace("__SOURCE_EXPORT_OFFSET__","+08:00")))
                .isInstanceOf(ScriptStatementFailedException.class).hasMessageContaining("DATABASE()");
        targetEmpty();
    }

    @ParameterizedTest @ValueSource(strings={"source-only-match","target-only-match","missing-target"})
    void sourceAndTargetRunOwnershipAreVerifiedIndependently(String corruption) {
        switch(corruption) {
            case "source-only-match" -> {legacy.update("UPDATE agent_research_export_audit SET user_id=2");legacy.update("UPDATE agent_run SET user_id=2 WHERE run_id=?",RUN);}
            case "target-only-match" -> {legacy.update("UPDATE agent_research_export_audit SET user_id=2");jdbc.update("UPDATE agent_run SET user_id=2 WHERE run_id=?",RUN);}
            case "missing-target" -> jdbc.update("DELETE FROM agent_run WHERE run_id=?",RUN);
            default -> throw new IllegalArgumentException(corruption);
        }
        assertThatThrownBy(this::migrate).isInstanceOf(ScriptStatementFailedException.class);targetEmpty();
    }

    @ParameterizedTest @ValueSource(strings={"extra-column","type","nullable","collation","default","unique-key","foreign-key","cascade","check","trigger"})
    void undeclaredSourceMetadataIsNeverSilentlyIgnored(String corruption) {
        switch(corruption) {
            case "extra-column" -> legacy.execute("ALTER TABLE agent_research_export_audit ADD extra_evidence VARCHAR(64) NULL");
            case "type" -> legacy.execute("ALTER TABLE agent_research_export_audit MODIFY payload_bytes BIGINT NOT NULL");
            case "nullable" -> legacy.execute("ALTER TABLE agent_research_export_audit MODIFY source_count INT NULL");
            case "collation" -> legacy.execute("ALTER TABLE agent_research_export_audit MODIFY export_id VARCHAR(36) COLLATE utf8mb4_unicode_ci NOT NULL");
            case "default" -> legacy.execute("ALTER TABLE agent_research_export_audit MODIFY format_version INT NOT NULL DEFAULT 1");
            case "unique-key" -> legacy.execute("ALTER TABLE agent_research_export_audit DROP INDEX uk_research_export");
            case "foreign-key" -> legacy.execute("ALTER TABLE agent_research_export_audit DROP FOREIGN KEY fk_research_export_run");
            case "cascade" -> {legacy.execute("ALTER TABLE agent_research_export_audit DROP FOREIGN KEY fk_research_export_run");legacy.execute("ALTER TABLE agent_research_export_audit ADD CONSTRAINT fk_research_export_run FOREIGN KEY(run_id) REFERENCES agent_run(run_id) ON DELETE CASCADE");}
            case "check" -> legacy.execute("ALTER TABLE agent_research_export_limit ADD CONSTRAINT new_source_check CHECK(export_count>=0)");
            case "trigger" -> legacy.execute("CREATE TRIGGER unknown_source_export BEFORE INSERT ON agent_research_export_audit FOR EACH ROW SET NEW.source_count=NEW.source_count");
            default -> throw new IllegalArgumentException(corruption);
        }
        assertThatThrownBy(this::migrate).isInstanceOf(ScriptStatementFailedException.class);targetEmpty();
    }

    @ParameterizedTest @ValueSource(strings={"hash","missing-count","legacy-source-space","legacy-key-space"})
    void equalCountsCannotHideChangedOrMissingReceiptFacts(String corruption) {
        if("hash".equals(corruption))jdbc.execute("CREATE TRIGGER corrupt_export_copy BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.content_sha256=REPEAT('f',64)");
        else if("missing-count".equals(corruption))jdbc.execute("CREATE TRIGGER corrupt_export_copy BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.payload_json=JSON_REMOVE(NEW.payload_json,'$.sourceCount')");
        else if("legacy-source-space".equals(corruption))jdbc.execute("CREATE TRIGGER corrupt_export_copy BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.legacy_source=CONCAT(NEW.legacy_source,' ')");
        else jdbc.execute("CREATE TRIGGER corrupt_export_copy BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.legacy_key=CONCAT(NEW.legacy_key,' ')");
        var failure=assertThatThrownBy(this::migrate).isInstanceOf(ScriptStatementFailedException.class);
        if(corruption.endsWith("-space"))failure.hasMessageContaining("LEFT JOIN audit_event");
        targetEmpty();
    }

    @Test void failedExportAuditRollsBackTheCounterAndNoFileIsReturned() throws Exception {
        migrate();
        jdbc.execute("ALTER TABLE audit_event ADD CONSTRAINT reject_new_export CHECK(kind<>'RESEARCH_EXPORT' OR resource_id='"+EXPORT+"')");
        assertThatThrownBy(()->exports().export(actor,RUN,true)).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(jdbc.queryForObject("SELECT counter_value FROM runtime_state WHERE namespace='RESEARCH_EXPORT_LIMIT'",Long.class)).isEqualTo(2);
        assertThat(jdbc.queryForObject("SELECT window_ends_at FROM runtime_state WHERE namespace='RESEARCH_EXPORT_LIMIT'",LocalDateTime.class)).isEqualTo(UTC.plusSeconds(60));
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='RESEARCH_EXPORT'",Long.class)).isEqualTo(1);
    }

    @Test void separateConnectionsConsumeTheFinalSlotOnlyOnce() throws Exception {
        migrate();var workers=Executors.newFixedThreadPool(2);var start=new CountDownLatch(1);
        try {
            Callable<Integer> attempt=()->{start.await();try{exports().export(actor,RUN,true);return 1;}catch(ResearchExportRateLimit.Limited expected){return 0;}};
            var first=workers.submit(attempt);var second=workers.submit(attempt);start.countDown();
            assertThat(first.get(15,TimeUnit.SECONDS)+second.get(15,TimeUnit.SECONDS)).isEqualTo(1);
            assertThat(jdbc.queryForObject("SELECT counter_value FROM runtime_state WHERE namespace='RESEARCH_EXPORT_LIMIT'",Long.class)).isEqualTo(1);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='RESEARCH_EXPORT'",Long.class)).isEqualTo(2);
        } finally {workers.shutdownNow();}
    }

    @Test void counterRequiresItsActualDataSourceTransactionAndCopyCannotOverwriteHistory() throws Exception {
        migrate();var limiter=new ResearchExportRateLimit(jdbc,new ResearchEvidenceProperties());
        assertThatThrownBy(()->limiter.consume(actor)).isInstanceOf(IllegalStateException.class);
        new TransactionTemplate(manager).executeWithoutResult(status->{limiter.consume(actor);status.setRollbackOnly();});
        assertThat(jdbc.queryForObject("SELECT counter_value FROM runtime_state WHERE namespace='RESEARCH_EXPORT_LIMIT'",Long.class)).isEqualTo(2);
        assertThatThrownBy(this::migrate).isInstanceOf(ScriptStatementFailedException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='RESEARCH_EXPORT'",Long.class)).isEqualTo(1);
    }
}
