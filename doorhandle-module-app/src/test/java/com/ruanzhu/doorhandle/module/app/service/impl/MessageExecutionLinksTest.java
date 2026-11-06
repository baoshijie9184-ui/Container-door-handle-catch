package com.ruanzhu.doorhandle.module.app.service.impl;

import com.ruanzhu.doorhandle.module.app.dto.chat.ChatMessageResponse;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import com.ruanzhu.doorhandle.module.app.testsupport.CompactMySqlFixture;
import com.ruanzhu.doorhandle.module.app.testsupport.FeatureMySql;
import com.ruanzhu.doorhandle.framework.persistence.chat.JdbcMessageEvidenceStore;
import com.ruanzhu.doorhandle.framework.persistence.chat.MessageEvidence;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import static org.assertj.core.api.Assertions.*;

/** Actual 29-table MySQL schema on an admitted ECS fixture; no embedded database fallback. */
@EnabledIfSystemProperty(named="doorhandle.feature.mysql.config",matches=".+")
class MessageExecutionLinksTest {
    JdbcTemplate jdbc;
    MessageExecutionLinks links;
    CompactMySqlFixture fixture;
    TenantContext alice=new TenantContext(1L,"alice");
    @BeforeEach void database()throws Exception{
        var source=FeatureMySql.source();fixture=new CompactMySqlFixture(source);jdbc=new JdbcTemplate(source);
        jdbc.update("INSERT INTO users(id,username,password) VALUES(1,'alice','fixture'),(2,'bob','fixture')");
        jdbc.update("INSERT INTO chat_session(session_id,user_id,username) VALUES ('s1',1,'alice'),('s2',2,'bob'),('s3',1,'alice')");
        jdbc.update("INSERT INTO chat_message(id,session_id,role,message_type,content) VALUES (11,'s1','assistant','TEXT','a'),(12,'s1','user','TEXT','b'),(13,'s2','assistant','TEXT','c'),(14,'s3','assistant','TEXT','d'),(15,'s1','assistant','TEXT','e')");
        for(var row:List.of(List.of("run-1",1,"s1","CHAT"),List.of("run-2",2,"s2","AGUI"),List.of("run-3",1,"s3","CHAT"),List.of("run-4",1,"s1","AGUI")))
            jdbc.update("INSERT INTO agent_run(run_id,user_id,session_id,main_agent,entry_point,request_key,status,default_model,policy_version,instance_id,started_at,heartbeat_at,lease_expires_at) VALUES(?,?,?,'main',?,?,'COMPLETED','fixture','v1','fixture',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",row.get(0),row.get(1),row.get(2),row.get(3),row.get(0));
        links=new MessageExecutionLinks(jdbc);
    }
    @AfterEach void close(){if(fixture!=null)fixture.close();}
    ChatMessageResponse message(long id,String session){var m=new ChatMessageResponse();m.setId(id);m.setSessionId(session);m.setRole("assistant");m.setMessageType("TEXT");m.setContent("正文保持原样");return m;}
    int count(){return jdbc.queryForObject("SELECT COUNT(*) FROM chat_message WHERE execution_run_id IS NOT NULL",Integer.class);}
    JdbcMessageEvidenceStore evidence(){return new JdbcMessageEvidenceStore(jdbc,new com.fasterxml.jackson.databind.ObjectMapper());}
    void transaction(Runnable action){new org.springframework.transaction.support.TransactionTemplate(new org.springframework.jdbc.datasource.DataSourceTransactionManager(jdbc.getDataSource())).executeWithoutResult(status->action.run());}
    void retainedEvidence(){links.bind(alice,"s1",11L,"run-1");transaction(()->{evidence().saveSnapshot(1,"s1",11,"{\"files\":[],\"business\":[]}");evidence().saveSources(1,"s1",11,"[]");});}

    @ParameterizedTest @ValueSource(strings={"message","session","user"})
    void directDeletionAndForeignKeyCascadesKeepAllOriginalEvidence(String parent){
        retainedEvidence();var before=jdbc.queryForList("SELECT * FROM audit_event ORDER BY id");
        switch(parent){case "message"->jdbc.update("DELETE FROM chat_message WHERE id=11");case "session"->jdbc.update("DELETE FROM chat_session WHERE session_id='s1'");case "user"->jdbc.update("DELETE FROM users WHERE id=1");default->throw new AssertionError(parent);}
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM chat_message WHERE id=11",Integer.class)).isZero();
        assertThat(jdbc.queryForList("SELECT * FROM audit_event ORDER BY id")).isEqualTo(before);
        assertThat(before).hasSize(3);
    }
    @Test void changingSessionPrimaryKeyKeepsOriginalEvidenceIdentityAndCurrentReadsFollowThePointer(){
        retainedEvidence();var before=jdbc.queryForList("SELECT * FROM audit_event ORDER BY id");
        jdbc.update("UPDATE chat_session SET session_id='renamed' WHERE session_id='s1'");
        var message=message(11,"renamed");links.hydrate(alice,"renamed",List.of(message));assertThat(message.getRunId()).isEqualTo("run-1");
        assertThat(evidence().loadSnapshot(1,"renamed",11)).isEqualTo("{\"files\":[],\"business\":[]}");
        assertThat(evidence().loadSources(1,"renamed",11)).isEqualTo("[]");
        transaction(()->assertThat(evidence().saveSources(1,"renamed",11,"[]")).isFalse());
        assertThat(jdbc.queryForList("SELECT * FROM audit_event ORDER BY id")).isEqualTo(before);
    }
    @Test void deletedMessageDoesNotReleaseTheOriginalGloballyUniqueRunBinding(){
        links.bind(alice,"s1",11L,"run-1");jdbc.update("DELETE FROM chat_message WHERE id=11");links.bind(alice,"s1",15L,"run-1");
        assertThat(count()).isZero();assertThat(jdbc.queryForObject("SELECT message_id FROM audit_event WHERE kind='MESSAGE_EXECUTION'",Long.class)).isEqualTo(11);
    }
    @Test void evidenceInsertFailureRollsBackTheMessageProjection(){
        jdbc.execute("ALTER TABLE audit_event ADD CONSTRAINT reject_snapshot CHECK(kind<>'MESSAGE_WORKSPACE_SNAPSHOT')");
        assertThatThrownBy(()->transaction(()->evidence().saveSnapshot(1,"s1",11,"{}"))).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(jdbc.queryForObject("SELECT snapshot_evidence_id FROM chat_message WHERE id=11",Long.class)).isNull();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event",Integer.class)).isZero();
    }
    @Test void projectionFailureRollsBackTheJustAppendedEvidence(){
        jdbc.execute("ALTER TABLE chat_message ADD CONSTRAINT reject_context CHECK(context_evidence_id IS NULL)");
        assertThatThrownBy(()->transaction(()->evidence().saveSources(1,"s1",11,"[]"))).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event",Integer.class)).isZero();
    }
    @Test void pointersCannotReadOrBindEvidenceOwnedByAnotherAccount(){
        retainedEvidence();long pointer=jdbc.queryForObject("SELECT snapshot_evidence_id FROM chat_message WHERE id=11",Long.class);
        assertThatThrownBy(()->jdbc.update("UPDATE chat_message SET snapshot_owner_user_id=2,snapshot_evidence_id=?,workspace_snapshot_json='{}',workspace_snapshot_sha256=REPEAT('a',64),workspace_snapshot_created_at=UTC_TIMESTAMP(6) WHERE id=13",pointer)).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(evidence().loadSnapshot(2,"s1",11)).isNull();
        assertThatThrownBy(()->transaction(()->evidence().saveSources(2,"s1",11,"[]"))).isInstanceOf(SecurityException.class);
    }
    @Test void nonNullApplicationMapperStillWritesEveryTypedEvidenceFieldAndStrictReplayIsIdempotent()throws Exception{
        var applicationJson=new ObjectMapper().setSerializationInclusion(JsonInclude.Include.NON_NULL);
        var store=new JdbcMessageEvidenceStore(jdbc,applicationJson);
        String snapshot="{\"files\":[],\"business\":[]}",sources="[]";
        transaction(()->{assertThat(store.bindExecution(1,"s1",11,"run-1")).isTrue();assertThat(store.saveSnapshot(1,"s1",11,snapshot)).isTrue();assertThat(store.saveSources(1,"s1",11,sources)).isTrue();});
        var strict=new ObjectMapper().enable(DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES);
        String execution=jdbc.queryForObject("SELECT payload_json FROM audit_event WHERE kind='MESSAGE_EXECUTION'",String.class);
        String workspace=jdbc.queryForObject("SELECT payload_json FROM audit_event WHERE kind='MESSAGE_WORKSPACE_SNAPSHOT'",String.class);
        String context=jdbc.queryForObject("SELECT payload_json FROM audit_event WHERE kind='MESSAGE_CONTEXT_SOURCES'",String.class);
        assertThat(strict.readTree(execution).has("legacyId")).isTrue();assertThat(strict.readTree(execution).get("legacyId").isNull()).isTrue();
        assertThat(strict.readTree(workspace).has("legacyId")).isTrue();assertThat(strict.readTree(workspace).get("legacyId").isNull()).isTrue();
        assertThat(strict.readValue(execution,MessageEvidence.ExecutionV1.class).legacyId()).isNull();
        assertThat(strict.readValue(workspace,MessageEvidence.WorkspaceSnapshotV1.class).snapshotJson()).isEqualTo(snapshot);
        assertThat(strict.readValue(context,MessageEvidence.ContextSourcesV1.class).sourcesJson()).isEqualTo(sources);
        // The protocol must not mutate the shared mapper used to serialize HTTP responses.
        assertThat(applicationJson.writeValueAsString(new MessageEvidence.ExecutionV1(null,"time","+00:00"))).doesNotContain("legacyId");
        var before=jdbc.queryForList("SELECT * FROM audit_event ORDER BY id");
        var fresh=new JdbcMessageEvidenceStore(jdbc,applicationJson);
        assertThat(fresh.executionLinks(1,"s1",List.of(11L))).containsEntry(11L,"run-1");
        assertThat(fresh.loadSnapshot(1,"s1",11)).isEqualTo(snapshot);assertThat(fresh.loadSources(1,"s1",11)).isEqualTo(sources);
        transaction(()->{assertThat(fresh.bindExecution(1,"s1",11,"run-1")).isTrue();assertThat(fresh.saveSnapshot(1,"s1",11,snapshot)).isFalse();assertThat(fresh.saveSources(1,"s1",11,sources)).isFalse();});
        assertThat(jdbc.queryForList("SELECT * FROM audit_event ORDER BY id")).isEqualTo(before);
    }
    @Test void workspaceSnapshotCopyWithNonNullMapperUsesIndependentEvidenceWithinTheActualBaselineTransaction(){
        retainedEvidence();var snapshots=new WorkspaceTurnSnapshotService(jdbc,new ObjectMapper().setSerializationInclusion(JsonInclude.Include.NON_NULL));
        transaction(()->snapshots.copy(1,"s1",11,"s1",15));
        assertThat(evidence().loadSnapshot(1,"s1",15)).isEqualTo("{\"files\":[],\"business\":[]}");
        // Read the new copy through the actual service, then replay the original immutable snapshot.
        transaction(()->snapshots.copy(1,"s1",15,"s1",11));
        jdbc.update("DELETE FROM chat_message WHERE id IN (11,15)");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='MESSAGE_WORKSPACE_SNAPSHOT'",Integer.class)).isEqualTo(2);
    }

    @Test void aFreshServiceRestoresTheExactPersistedMessageLink(){
        links.bind(alice,"s1",11L,"run-1");assertThat(count()).isEqualTo(1);
        var saved=message(11,"s1");new MessageExecutionLinks(jdbc).hydrate(alice,"s1",List.of(saved));
        assertThat(saved.getRunId()).isEqualTo("run-1");assertThat(saved.getContent()).isEqualTo("正文保持原样");
    }
    @Test void rejectsCrossAccountCrossSessionAndUserMessages(){
        links.bind(alice,"s1",11L,"run-2");links.bind(alice,"s1",11L,"run-3");
        links.bind(alice,"s2",13L,"run-2");links.bind(alice,"s1",12L,"run-1");links.bind(alice,"s1",14L,"run-1");
        assertThat(count()).isZero();
    }
    @Test void doesNotAssociateARunningOrSpecialistRunButAllowsASavedWaitingReply(){
        jdbc.update("UPDATE agent_run SET status='RUNNING' WHERE run_id='run-1'");links.bind(alice,"s1",11L,"run-1");assertThat(count()).isZero();
        jdbc.update("UPDATE agent_run SET status='COMPLETED',entry_point='CHILD' WHERE run_id='run-1'");links.bind(alice,"s1",11L,"run-1");assertThat(count()).isZero();
        jdbc.update("UPDATE agent_run SET status='INTERRUPTED',entry_point='AGUI' WHERE run_id='run-1'");links.bind(alice,"s1",11L,"run-1");assertThat(count()).isEqualTo(1);
    }
    @Test void repeatedBindingsNeverReassignAMessageOrShareOneRunBetweenReplies(){
        links.bind(alice,"s1",11L,"run-1");links.bind(alice,"s1",11L,"run-1");links.bind(alice,"s1",11L,"run-4");links.bind(alice,"s1",15L,"run-1");
        assertThat(count()).isEqualTo(1);assertThat(jdbc.queryForObject("SELECT execution_run_id FROM chat_message WHERE id=11",String.class)).isEqualTo("run-1");
    }
    @Test void historyReadsCheckOwnershipAndDoNotGuessFromAnotherMessage(){
        links.bind(alice,"s1",11L,"run-1");
        var wrong=message(11,"s1");links.hydrate(new TenantContext(2L,"bob"),"s1",List.of(wrong));assertThat(wrong.getRunId()).isNull();
        var legacy=message(15,"s1");links.hydrate(alice,"s1",List.of(legacy));assertThat(legacy.getRunId()).isNull();
        jdbc.update("UPDATE chat_session SET user_id=2 WHERE session_id='s1'");links.hydrate(alice,"s1",List.of(wrong));assertThat(wrong.getRunId()).isNull();
    }
    @Test void missingMigrationKeepsTheMessageUsableAndDoesNotThrow(){
        jdbc.execute("ALTER TABLE chat_message RENAME COLUMN execution_run_id TO unavailable_execution_run_id");var m=message(11,"s1");
        assertThatCode(()->{links.hydrate(alice,"s1",List.of(m));links.bind(alice,"s1",11L,"run-1");}).doesNotThrowAnyException();
        assertThat(m.getContent()).isEqualTo("正文保持原样");assertThat(m.getRunId()).isNull();
    }
    @Test void batchesVisibleMessageIdsInsteadOfQueryingEveryBubble(){
        links.bind(alice,"s1",11L,"run-1");var spy=org.mockito.Mockito.spy(jdbc);var reader=new MessageExecutionLinks(spy);
        var page=new ArrayList<ChatMessageResponse>();for(long id=11;id<=311;id++)page.add(message(id,"s1"));reader.hydrate(alice,"s1",page);
        assertThat(page.get(0).getRunId()).isEqualTo("run-1");
        assertThat(org.mockito.Mockito.mockingDetails(spy).getInvocations().stream().filter(inv->inv.getMethod().getName().equals("queryForList")).count()).isEqualTo(2);
    }
    @Test void archiveAndRuntimeMigrationCopiesMatchAndDoNotBackfillHistory()throws Exception{
        String archive=Files.readString(Path.of("../sql/mysql/migration-V66-chat-message-execution.sql"));
        try(var input=getClass().getResourceAsStream("/db/migration-V66-chat-message-execution.sql")){
            assertThat(new String(Objects.requireNonNull(input).readAllBytes(),StandardCharsets.UTF_8)).isEqualTo(archive);
        }
        assertThat(archive).contains("CREATE TABLE IF NOT EXISTS","idx_message_execution_owner").doesNotContain("INSERT INTO","UPDATE chat_message","ALTER TABLE chat_message");
    }
}
