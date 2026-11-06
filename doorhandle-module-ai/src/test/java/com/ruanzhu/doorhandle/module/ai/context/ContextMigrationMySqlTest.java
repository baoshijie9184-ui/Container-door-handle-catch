package com.ruanzhu.doorhandle.module.ai.context;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.ai.testsupport.CompactContextMySqlFixture;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import static org.assertj.core.api.Assertions.*;

/** Native MySQL only on independently admitted ECS schemas; never creates a database or runs locally. */
@EnabledIfSystemProperty(named="doorhandle.context.source.config",matches=".+")
class ContextMigrationMySqlTest {
    private CompactContextMySqlFixture fixture;
    private JdbcTemplate source,target;
    private final ObjectMapper json=new ObjectMapper();
    private static final long LARGE=9_007_199_254_740_993L;
    private static final long REVISION=2_147_483_650L;
    private static final String SESSION="deleted-session",SCOPE="scope-"+"x".repeat(154);
    private static final String SOURCES="[ { \"kind\" : \"ROLE\", \"resourceId\" : \"INSPECTOR\", \"version\" : \"\" } ]  ";
    private static final String INITIAL="{\"context\":[],\"unicode\":\"原文𝄞\\nquoted \\\"value\\\"\"}  ";
    private static final String SUMMARY="保留原文字串\n{not required to reserialize: \"摘要\"}  ";

    @BeforeEach void setup()throws Exception{
        fixture=new CompactContextMySqlFixture("doorhandle.context.mysql.config","doorhandle_agent_verify_","ecsit_",true);
        source=fixture.source();target=fixture.jdbc();
        source.update("INSERT INTO agent_context_head(user_id,session_id,agent_scope,revision,summary_id) VALUES(901,?,?,?,'summary-1')",SESSION,SCOPE,REVISION);
        String boot=ContextDigests.bootstrapHash(json,901,SESSION,SCOPE,"task-1",8,INITIAL);
        source.update("INSERT INTO agent_context_bootstrap(user_id,session_id,logical_task_id,agent_scope,history_through,initial_state,initial_sha256,initialized) VALUES(901,?,'task-1',?,8,?,?,1)",SESSION,SCOPE,INITIAL,boot);
        String digest=ContextDigests.summaryHash(json,SUMMARY,INITIAL,SOURCES,SCOPE,8,"A".repeat(64),INITIAL);
        source.update("INSERT INTO agent_context_summary(id,summary_id,user_id,session_id,agent_scope,revision,status,covered_through,history_sha256,summary_json,summary_sha256,message_state,sources_json,policy_version,run_id,before_chars,after_chars,original_state,created_at) VALUES(?,'summary-1',901,?,? ,?,'ACTIVE',8,?,?,?,?,?,'durable-context-v1','deleted-run',1000,100,?,'2025-01-02 03:04:05.123456')",LARGE,SESSION,SCOPE,REVISION,"A".repeat(64),SUMMARY,digest,INITIAL,SOURCES,INITIAL);
        source.update("INSERT INTO agent_context_origin(user_id,session_id,agent_scope,call_key,logical_task_id,run_id,sources_json,sources_sha256) VALUES(901,?,?,?,'task-1','deleted-run',?,?)",SESSION,SCOPE,"b".repeat(64),SOURCES,ContextDigests.hash(SOURCES));
        // Historical forks did not create origin rows. Preserve this receipt without fabricating one.
        source.update("INSERT INTO agent_context_offload(id,offload_id,user_id,session_id,agent_scope,call_id,file_id,content_sha256,byte_length,sources_json,sources_sha256,created_at) VALUES(?,'offload-1',901,?,?,'old-fork-call','deleted-file',?,37,?,?,'2025-01-02 03:04:05.000001')",LARGE,SESSION,SCOPE,"C".repeat(64),SOURCES,ContextDigests.hash(SOURCES));
        source.update("INSERT INTO agent_context_audit(id,user_id,session_id,agent_scope,resource_id,action,content_sha256,created_at) VALUES(?,901,?,?,'deleted-file','READ_CONTEXT',?,'2025-01-02 03:04:05.123456')",LARGE,SESSION,SCOPE,"D".repeat(64));
    }
    @AfterEach void close()throws Exception{if(fixture!=null)fixture.close();}

    @Test void preservesAllSixtyFieldsOriginalJsonShaOrphansAndUnknownTimes()throws Exception{
        var before=snapshot();var seq=sequences();fixture.migrate("+08:00");
        var persistence=new DurableContextPersistence(target,new ObjectMapper().setSerializationInclusion(JsonInclude.Include.NON_NULL));
        var summary=persistence.activeSummary(901,SESSION,"summary-1");
        assertThat(summary).isNotNull();assertThat(summary.body().contextRevision()).isEqualTo(REVISION);
        assertThat(summary.summary()).isEqualTo(SUMMARY);assertThat(summary.sources()).isEqualTo(SOURCES);
        assertThat(summary.body().messageState()).isEqualTo(INITIAL);assertThat(summary.body().originalState()).isEqualTo(INITIAL);
        assertThat(summary.body().agentScope()).isEqualTo(SCOPE);assertThat(summary.body().historySha256()).isEqualTo("A".repeat(64));
        assertThat(summary.body().createdAtSource()).isEqualTo("2025-01-02 03:04:05.123456");assertThat(summary.body().sourceUtcOffset()).isEqualTo("+08:00");
        assertThat(summary.created().toString()).isEqualTo("2025-01-01T19:04:05.123456");
        assertThat(target.queryForObject("SELECT updated_at FROM content_asset WHERE asset_kind='CONTEXT_SUMMARY'",Object.class)).isNull();
        var bootstrap=persistence.bootstrap(901,SESSION,"task-1",false).orElseThrow();
        assertThat(bootstrap.ready()).isTrue();assertThat(bootstrap.body().initialState()).isEqualTo(INITIAL);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM runtime_state WHERE created_at IS NOT NULL OR updated_at IS NOT NULL",Integer.class)).isZero();
        assertThat(persistence.origin(901,SESSION,SCOPE,"b".repeat(64)).body().sourcesJson()).isEqualTo(SOURCES);
        var offload=persistence.offloads(901,SESSION,SCOPE,null,"deleted-file",2,false).get(0);
        assertThat(offload.body().lineageKind()).isEqualTo("LEGACY");assertThat(offload.body().sourceOffloadId()).isNull();
        assertThat(offload.body().throughMessageId()).isNull();assertThat(offload.body().contentSha256()).isEqualTo("C".repeat(64));
        assertThat(target.queryForObject("SELECT COUNT(*) FROM content_link WHERE link_kind='TOOL_SOURCE' AND created_at IS NOT NULL",Integer.class)).isZero();
        var audit=target.queryForMap("SELECT * FROM audit_event WHERE kind='CONTEXT'");
        assertThat(audit.get("actor_user_id")).isNull();assertThat(audit.get("legacy_key")).isEqualTo(Long.toString(LARGE));
        assertThat(target.queryForObject("SELECT COUNT(*) FROM users",Integer.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM chat_session",Integer.class)).isZero();
        assertThat(snapshot()).isEqualTo(before);assertThat(sequences()).isEqualTo(seq);
    }

    @Test void keepsMismatchedHeadAndHistoricalForkWithoutForgingParentRows()throws Exception{
        source.update("UPDATE agent_context_head SET summary_id='missing-summary'");fixture.migrate("+00:00");
        var store=new DurableContextPersistence(target,json);
        assertThat(store.current(901,SESSION,SCOPE)).isNull();
        assertThat(store.activeSummary(901,SESSION,"summary-1")).isNotNull();
        assertThat(store.offloads(901,SESSION,SCOPE,"old-fork-call",null,2,false)).hasSize(1);
        assertThat(store.origin(901,SESSION,SCOPE,"old-fork-call")).isNull();
    }

    @ParameterizedTest @ValueSource(strings={
        "ALTER TABLE agent_context_summary ADD COLUMN unknown_fact TEXT NULL",
        "ALTER TABLE agent_context_origin DROP INDEX idx_context_origin_task",
        "ALTER TABLE agent_context_head ADD UNIQUE KEY unexpected(summary_id)",
        "ALTER TABLE agent_context_offload MODIFY agent_scope VARCHAR(160) COLLATE utf8mb4_0900_ai_ci NOT NULL",
        "ALTER TABLE agent_context_bootstrap ALTER COLUMN initialized SET DEFAULT 1",
        "CREATE TRIGGER unreviewed BEFORE INSERT ON agent_context_audit FOR EACH ROW SET NEW.action='changed'"})
    void rejectsUnknownSourceShapeBeforeImport(String change)throws Exception{source.execute(change);reject();}

    @ParameterizedTest @ValueSource(strings={
        "UPDATE agent_context_bootstrap SET initialized=2",
        "UPDATE agent_context_bootstrap SET initial_sha256=REPEAT('0',64)",
        "UPDATE agent_context_summary SET summary_json=CONCAT(summary_json,'changed')",
        "UPDATE agent_context_summary SET status='UNREVIEWED'",
        "UPDATE agent_context_origin SET sources_sha256=REPEAT('0',64)",
        "UPDATE agent_context_offload SET sources_json='not-json'",
        "UPDATE agent_context_audit SET created_at='9999-01-01 00:00:00'"})
    void rejectsInvalidDigestStateAndUnsupportedUtcConversionWithoutSourceWrites(String change)throws Exception{source.update(change);reject();}

    @ParameterizedTest @ValueSource(strings={
        "CREATE TRIGGER corrupt_context BEFORE INSERT ON content_revision FOR EACH ROW SET NEW.content_text=CONCAT(NEW.content_text,'changed')",
        "CREATE TRIGGER corrupt_context BEFORE INSERT ON content_link FOR EACH ROW SET NEW.subject_id=CONCAT(NEW.subject_id,'changed')",
        "CREATE TRIGGER corrupt_context BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.quantity=1,NEW.unit='BYTES'",
        "CREATE TRIGGER corrupt_context BEFORE INSERT ON audit_event FOR EACH ROW UPDATE runtime_state SET revision=99 WHERE namespace='CONTEXT_HEAD'"})
    void tailComparisonRollsBackEarlierRowsWhenAnyTargetIsMutated(String trigger)throws Exception{fixture.installTarget(trigger+";");reject();}

    @Test void closedRecordsRejectUnknownOrMissingFieldsEvenUnderApplicationNonNullPolicy()throws Exception{
        fixture.migrate("+08:00");
        var store=new DurableContextPersistence(target,new ObjectMapper().setSerializationInclusion(JsonInclude.Include.NON_NULL));
        var saved=store.offloads(901,SESSION,null,null,null,2,false).get(0).body();
        assertThat(saved.sourceSessionId()).isNull();assertThat(saved.throughMessageId()).isNull();
        var strict=DurableContextProtocols.mapper(new ObjectMapper().setSerializationInclusion(JsonInclude.Include.NON_NULL));
        String complete=DurableContextProtocols.encode(strict,saved);
        var missing=json.readTree(complete);((com.fasterxml.jackson.databind.node.ObjectNode)missing).remove("sourceSessionId");
        assertThatThrownBy(()->strict.readValue(missing.toString(),DurableContextProtocols.OffloadEvidenceV1.class)).isInstanceOf(com.fasterxml.jackson.core.JsonProcessingException.class);
        var unknown=json.readTree(complete);((com.fasterxml.jackson.databind.node.ObjectNode)unknown).put("freeFormExtension","forbidden");
        assertThatThrownBy(()->strict.readValue(unknown.toString(),DurableContextProtocols.OffloadEvidenceV1.class)).isInstanceOf(com.fasterxml.jackson.core.JsonProcessingException.class);
    }

    @Test void bootstrapAndCheckpointShareOneActualTransactionAndOriginalReservationWins()throws Exception{
        fixture.migrate("+08:00");
        target.update("INSERT INTO users(id,username,password) VALUES(1,'alice','fixture')");
        target.update("INSERT INTO chat_session(session_id,user_id,username,title) VALUES('live',1,'alice','live')");
        var persistence=new DurableContextPersistence(target,json);
        var tx=new TransactionTemplate(new DataSourceTransactionManager(fixture.dataSource()));
        String hash=ContextDigests.bootstrapHash(json,1,"live","main","task",0,INITIAL);
        tx.executeWithoutResult(status->{assertThat(persistence.reserve(1,"live","task",0,new DurableContextProtocols.ContextBootstrapV1("main",INITIAL,hash,null)).created()).isTrue();});
        assertThatThrownBy(()->tx.executeWithoutResult(status->{
            var boot=persistence.bootstrap(1,"live","task",true).orElseThrow();persistence.initialized(boot);
            throw new IllegalStateException("checkpoint write failed");
        })).isInstanceOf(IllegalStateException.class);
        assertThat(persistence.bootstrap(1,"live","task",false).orElseThrow().ready()).isFalse();
        tx.executeWithoutResult(status->{var duplicate=persistence.reserve(1,"live","task",0,new DurableContextProtocols.ContextBootstrapV1("main",INITIAL,hash,null));assertThat(duplicate.created()).isFalse();});
    }

    private Map<String,List<Map<String,Object>>> snapshot(){
        var rows=new java.util.LinkedHashMap<String,List<Map<String,Object>>>();
        for(String table:List.of("agent_context_head","agent_context_summary","agent_context_offload","agent_context_origin","agent_context_bootstrap","agent_context_audit"))rows.put(table,source.queryForList("SELECT * FROM "+table+" ORDER BY user_id,session_id"));
        return rows;
    }
    private List<Map<String,Object>> sequences(){return source.queryForList("SELECT table_name,auto_increment FROM information_schema.tables WHERE table_schema=DATABASE() ORDER BY table_name");}
    private void reject()throws Exception{
        var before=snapshot();var seq=sequences();assertThatThrownBy(()->fixture.migrate("+08:00")).isInstanceOf(Exception.class);
        assertThat(snapshot()).isEqualTo(before);assertThat(sequences()).isEqualTo(seq);
        for(String table:List.of("runtime_state","content_asset","content_revision","content_link","audit_event"))assertThat(target.queryForObject("SELECT COUNT(*) FROM "+table,Integer.class)).isZero();
    }
}
