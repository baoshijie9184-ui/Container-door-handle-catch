package com.ruanzhu.doorhandle.module.app.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.ruanzhu.doorhandle.framework.persistence.chat.JdbcMessageEvidenceStore;
import com.ruanzhu.doorhandle.framework.persistence.chat.MessageEvidence;
import com.ruanzhu.doorhandle.module.app.testsupport.ChatEvidenceMigrationFixture;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.jdbc.core.JdbcTemplate;
import static org.assertj.core.api.Assertions.*;

/** Real dual-schema copy, including historical evidence with no current message/account/run. */
@EnabledIfSystemProperty(named="doorhandle.chat-evidence.source.config",matches=".+")
class CompactChatMigrationMySqlTest {
    ChatEvidenceMigrationFixture fixture;JdbcTemplate source,target;
    static final String SNAPSHOT="{\"files\":[], \"business\":[]}",SOURCES="[ {\"kind\":\"ROLE\",\"resourceId\":\"INSPECTOR\",\"version\":\"\"} ]";
    final ObjectMapper json=new ObjectMapper().enable(DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES);
    @BeforeEach void start()throws Exception{fixture=new ChatEvidenceMigrationFixture();source=fixture.source();target=fixture.target();}
    @AfterEach void close()throws Exception{if(fixture!=null)fixture.close();}
    private void seed(){
        target.update("INSERT INTO users(id,username,password) VALUES(1,'alice','fixture')");
        target.update("INSERT INTO chat_session(session_id,user_id,username) VALUES('source',1,'alice')");
        target.update("INSERT INTO chat_message(id,session_id,role,message_type,content) VALUES(11,'source','assistant','TEXT','原正文'),(12,'source','assistant','TEXT','另一条')");
        source.update("INSERT INTO agent_message_execution(id,user_id,session_id,message_id,run_id,created_at) VALUES(81,1,'source',11,'run-1','2026-10-17 12:34:56.123456'),(82,999,'missing',9000,'missing-run','2026-10-17 12:34:56.123456')");
        source.update("INSERT INTO agent_workspace_turn_snapshot(id,user_id,session_id,message_id,snapshot_json,snapshot_sha256,created_at) VALUES(91,1,'source',11,?,UPPER(SHA2(?,256)),'2026-10-17 12:34:56.654321'),(92,999,'missing',9000,?,SHA2(?,256),'2026-10-17 12:34:56.654321'),(93,2,'source',11,?,SHA2(?,256),'2026-10-17 12:34:56.654321')",SNAPSHOT,SNAPSHOT,SNAPSHOT,SNAPSHOT,SNAPSHOT,SNAPSHOT);
        source.update("INSERT INTO agent_context_turn VALUES(1,'source',11,?,SHA2(?,256)),(999,'missing',9000,?,SHA2(?,256)),(2,'source',11,?,SHA2(?,256))",SOURCES,SOURCES,SOURCES,SOURCES,SOURCES,SOURCES);
        source.execute("ALTER TABLE agent_message_execution AUTO_INCREMENT=10000");source.execute("ALTER TABLE agent_workspace_turn_snapshot AUTO_INCREMENT=20000");
    }
    private Map<String,List<Map<String,Object>>> snapshot(){return Map.of(
            "execution",source.queryForList("SELECT * FROM agent_message_execution ORDER BY id"),
            "workspace",source.queryForList("SELECT * FROM agent_workspace_turn_snapshot ORDER BY id"),
            "context",source.queryForList("SELECT * FROM agent_context_turn ORDER BY user_id,session_id,message_id"),
            "sequenceReceipt",source.queryForList("SELECT table_name,auto_increment FROM information_schema.tables WHERE table_schema=DATABASE() ORDER BY table_name"));}
    private void assertEmptyImport(){assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event",Long.class)).isZero();assertThat(target.queryForObject("SELECT COUNT(*) FROM chat_message WHERE execution_evidence_id IS NOT NULL OR snapshot_evidence_id IS NOT NULL OR context_evidence_id IS NOT NULL",Long.class)).isZero();}

    @Test void allEighteenColumnsAndOrphansRemainIndependentAndOnlyExactCurrentMessagesGetProjections()throws Exception{
        seed();var original=snapshot();fixture.migrate("+08:00");assertThat(snapshot()).isEqualTo(original);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event",Long.class)).isEqualTo(8);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event WHERE owner_user_id=999",Long.class)).isEqualTo(3);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM users WHERE id=999",Long.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM agent_run",Long.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='MESSAGE_CONTEXT_SOURCES' AND occurred_at IS NULL",Long.class)).isEqualTo(3);
        var execution=target.queryForMap("SELECT * FROM audit_event WHERE legacy_source='agent_message_execution' AND legacy_key='81'");
        assertThat(execution).containsEntry("owner_user_id",1L).containsEntry("session_id","source").containsEntry("message_id",11L).containsEntry("run_id","run-1").containsEntry("actor_user_id",null);
        assertThat(json.readValue((String)execution.get("payload_json"),MessageEvidence.ExecutionV1.class)).isEqualTo(new MessageEvidence.ExecutionV1("81","2026-10-17 12:34:56.123456","+08:00"));
        assertThat(target.queryForObject("SELECT occurred_at FROM audit_event WHERE legacy_source='agent_message_execution' AND legacy_key='81'",LocalDateTime.class)).isEqualTo(LocalDateTime.parse("2026-10-17T04:34:56.123456"));
        var workspace=target.queryForMap("SELECT * FROM audit_event WHERE legacy_source='agent_workspace_turn_snapshot' AND legacy_key='91'");
        assertThat(json.readValue((String)workspace.get("payload_json"),MessageEvidence.WorkspaceSnapshotV1.class)).isEqualTo(new MessageEvidence.WorkspaceSnapshotV1("91",SNAPSHOT,"2026-10-17 12:34:56.654321","+08:00"));
        assertThat(workspace.get("content_sha256")).isEqualTo(source.queryForObject("SELECT snapshot_sha256 FROM agent_workspace_turn_snapshot WHERE id=91",String.class));
        var reader=new JdbcMessageEvidenceStore(target,json);assertThat(reader.loadSnapshot(1,"source",11)).isEqualTo(SNAPSHOT);assertThat(reader.loadSources(1,"source",11)).isEqualTo(SOURCES);
        assertThat(reader.executionLinks(1,"source",List.of(11L))).containsEntry(11L,"run-1");
        assertThat(target.queryForObject("SELECT snapshot_evidence_id FROM chat_message WHERE id=12",Long.class)).isNull();
        assertThatThrownBy(()->fixture.migrate("+08:00")).isInstanceOf(Exception.class);assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event",Long.class)).isEqualTo(8);
    }
    @Test void deletedMessagesDoNotMakeTheirHistoricalEvidenceUnmigratable()throws Exception{
        seed();target.update("DELETE FROM chat_session WHERE session_id='source'");var original=snapshot();fixture.migrate("+08:00");
        assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event",Long.class)).isEqualTo(8);assertThat(snapshot()).isEqualTo(original);
    }
    @Test void originalContextIdentityIsNotAHashOnlySurrogate()throws Exception{
        seed();fixture.migrate("+08:00");
        assertThat(target.queryForList("SELECT owner_user_id,session_id,message_id,legacy_key FROM audit_event WHERE kind='MESSAGE_CONTEXT_SOURCES' ORDER BY owner_user_id"))
                .anySatisfy(row->assertThat(row).containsEntry("owner_user_id",999L).containsEntry("session_id","missing").containsEntry("message_id",9000L).containsEntry("legacy_key","999:7:missing:9000"));
    }
    @ParameterizedTest @ValueSource(strings={"unknown_column","collation","bad_hash","missing_field","legacy_space","projection"})
    void unknownSourceShapesAndChangedTargetValuesStopAndRollBackWithoutSourceChanges(String mutation){
        seed();switch(mutation){
            case "unknown_column"->source.execute("ALTER TABLE agent_context_turn ADD unknown_field INT NULL");
            case "collation"->source.execute("ALTER TABLE agent_context_turn MODIFY session_id VARCHAR(128) COLLATE utf8mb4_0900_ai_ci NOT NULL");
            case "bad_hash"->source.update("UPDATE agent_workspace_turn_snapshot SET snapshot_sha256=REPEAT('0',64) WHERE id=91");
            case "missing_field"->target.execute("CREATE TRIGGER damage_evidence BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.payload_json=IF(NEW.kind='MESSAGE_WORKSPACE_SNAPSHOT',JSON_REMOVE(NEW.payload_json,'$.createdAtSource'),NEW.payload_json)");
            case "legacy_space"->target.execute("CREATE TRIGGER damage_evidence BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.legacy_source=CONCAT(NEW.legacy_source,' ')");
            case "projection"->target.execute("CREATE TRIGGER damage_projection BEFORE UPDATE ON chat_message FOR EACH ROW SET NEW.workspace_snapshot_json=IF(NEW.snapshot_evidence_id IS NOT NULL,'{}',NEW.workspace_snapshot_json)");
            default->throw new AssertionError(mutation);
        }
        var original=snapshot();assertThatThrownBy(()->fixture.migrate("+08:00")).isInstanceOf(Exception.class);assertEmptyImport();assertThat(snapshot()).isEqualTo(original);
    }
    @Test void unknownSourceOffsetIsRejectedBeforeCopying(){seed();assertThatThrownBy(()->fixture.migrate("SYSTEM")).isInstanceOf(IllegalArgumentException.class);assertEmptyImport();}
    @ParameterizedTest @CsvSource({"+00:00,2026-10-17T12:34:56.123456","-05:30,2026-10-17T18:04:56.123456"})
    void evidencedZeroAndNegativeOffsetsKeepTheExactUtcInstantAndOriginalText(String offset,String expected)throws Exception{
        seed();var original=snapshot();fixture.migrate(offset);
        assertThat(target.queryForObject("SELECT occurred_at FROM audit_event WHERE legacy_source='agent_message_execution' AND legacy_key='81'",LocalDateTime.class)).isEqualTo(LocalDateTime.parse(expected));
        String payload=target.queryForObject("SELECT payload_json FROM audit_event WHERE legacy_source='agent_message_execution' AND legacy_key='81'",String.class);
        assertThat(json.readValue(payload,MessageEvidence.ExecutionV1.class)).isEqualTo(new MessageEvidence.ExecutionV1("81","2026-10-17 12:34:56.123456",offset));
        assertThat(snapshot()).isEqualTo(original);
    }
    @ParameterizedTest @ValueSource(strings={"agent_message_execution","agent_workspace_turn_snapshot"})
    void outOfRangeDatetimeCannotBeRelabelledUtcAndLeavesNoPartialImport(String table){
        seed();source.update("UPDATE "+table+" SET created_at='9999-01-01 12:34:56.123456'");
        var original=snapshot();var messages=target.queryForList("SELECT * FROM chat_message ORDER BY id");
        assertThatThrownBy(()->fixture.migrate("+08:00")).isInstanceOf(Exception.class);
        assertEmptyImport();assertThat(snapshot()).isEqualTo(original);
        assertThat(target.queryForList("SELECT * FROM chat_message ORDER BY id")).isEqualTo(messages);
    }
}
