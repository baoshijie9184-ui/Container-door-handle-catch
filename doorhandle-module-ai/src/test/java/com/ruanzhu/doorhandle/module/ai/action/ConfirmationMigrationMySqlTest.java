package com.ruanzhu.doorhandle.module.ai.action;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.ai.testsupport.CompactActionMySqlFixture;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.jdbc.core.JdbcTemplate;
import static org.assertj.core.api.Assertions.*;

/** Native MySQL: three historical sources in a separate, independently admitted ECS schema. */
@EnabledIfSystemProperty(named="doorhandle.action.source.config",matches=".+")
class ConfirmationMigrationMySqlTest {
    private CompactActionMySqlFixture fixture;
    private JdbcTemplate source,target;
    private final ObjectMapper json=new ObjectMapper();
    private static final long LARGE_ID=9_007_199_254_740_993L;
    private static final String RAW="不是 JSON\n{unfinished: \"quoted\"}\r\n保留尾空格  ";

    @BeforeEach void setup()throws Exception{
        fixture=new CompactActionMySqlFixture("doorhandle.action.mysql.config","doorhandle_agent_verify_","ecsit_",true);
        source=fixture.source();target=fixture.jdbc();
        for(var db:List.of(source,target)){
            db.update("INSERT INTO users(id,username,password) VALUES(1,'alice','fixture')");
            db.update("INSERT INTO chat_session(session_id,user_id,username,title) VALUES('Session-Original',1,'alice','原会话')");
        }
        target.update("INSERT INTO audit_event(id,event_id,kind,action,payload_version,payload_json) VALUES(700,'unrelated-audit','KNOWLEDGE','EXISTING',1,'{}')");
        proposal("shared-action","a".repeat(64),"PENDING",null);
        proposal("uncertain","B".repeat(64),"NEEDS_REVIEW","null");
        proposal("completed","c".repeat(64),"SUCCEEDED","{\"taskId\":\"old-task\",\"after\":null}");
        source.update("INSERT INTO agent_action_audit(id,action_id,user_id,run_id,event_type,actor_role,resource_id,arguments_digest,policy_version,result,reason_code,occurred_at) VALUES(?,'shared-action',901,'deleted-run','CONFIRMATION_CREATED','SUPERVISOR','old-task',?,'legacy-policy','PENDING',NULL,'2025-01-02 03:04:05.123456')",LARGE_ID,"a".repeat(64));
        // Audit may outlive its proposal/run/user: the original source has no such FKs.
        source.update("INSERT INTO agent_action_audit(id,action_id,user_id,run_id,event_type,actor_role,resource_id,arguments_digest,policy_version,result,reason_code,occurred_at) VALUES(91,'deleted-action',902,'deleted-run','TOOL_EXECUTION_STARTED','INSPECTOR','old-task',?,'legacy-policy','EXECUTING','UNKNOWN','2025-01-02 03:04:05.000001')","D".repeat(64));
        source.update("INSERT INTO chat_pending_action(id,action_id,session_id,action_type,action_payload_json,status,created_at,confirmed_at,error_message) VALUES(?,'shared-action','session-original','OLD_ACTION',?,'UNKNOWN',NULL,'2025-01-02 03:04:05','原始错误  ')",LARGE_ID,RAW);
        source.update("INSERT INTO chat_pending_action(id,action_id,session_id,action_type,action_payload_json,status,created_at,confirmed_at,error_message) VALUES(2,'Résumé','Session-Original','',?,'Pending','2025-01-02 03:04:05',NULL,NULL)","null");
    }
    private void proposal(String id,String hash,String status,String result){
        source.update("INSERT INTO agent_pending_action(action_id,user_id,run_id,session_id,call_id,operation,resource_id,resource_version,arguments_digest,command_json,before_json,result_json,policy_version,status,version,reason_code,created_at,expires_at,decided_at) VALUES(?,901,'deleted-run','deleted-session',NULL,'ASSIGN_QUALITY_TASK','old-task','version-7',?,CAST(? AS JSON),CAST(? AS JSON),CAST(? AS JSON),'legacy-policy',?,7,'reason','2025-01-02 03:04:05.123456','2025-01-02 03:14:05.123456','2025-01-02 03:05:00.654321')",id,hash,"{\"taskId\":\"old-task\",\"inspectionStation\":\"站点  \",\"assignee\":\"alice\",\"supervisor\":null,\"remark\":\"旧参数\"}","{\"inspectionStation\":null,\"assignee\":null,\"supervisor\":null,\"remark\":null,\"status\":\"DETECTED\"}",result,status);
    }
    @AfterEach void close()throws Exception{if(fixture!=null)fixture.close();}

    @Test void preservesAllFortyFieldsOrphansRawTextAndUnknownTimesWithDistinctIdentities()throws Exception{
        var original=snapshot();var sequences=sequences();fixture.migrate("+08:00");
        var store=new AgentActionPersistence(target,new ObjectMapper().setSerializationInclusion(JsonInclude.Include.NON_NULL));
        var row=store.find(901,"shared-action",false);
        assertThat(row).isNotNull();assertThat(row.version()).isEqualTo(7);assertThat(row.userId()).isEqualTo(901);
        assertThat(row.runId()).isEqualTo("deleted-run");assertThat(row.sessionId()).isEqualTo("deleted-session");
        assertThat(row.proposal().commandJson()).isEqualTo(source.queryForObject("SELECT CAST(command_json AS CHAR) FROM agent_pending_action WHERE action_id='shared-action'",String.class));
        assertThat(row.proposal().beforeJson()).isEqualTo(source.queryForObject("SELECT CAST(before_json AS CHAR) FROM agent_pending_action WHERE action_id='shared-action'",String.class));
        assertThat(row.proposal().callId()).isNull();assertThat(row.proposal().legacyCreatedAt()).isEqualTo("2025-01-02 03:04:05.123456");
        assertThat(row.proposal().sourceUtcOffset()).isEqualTo("+08:00");assertThat(row.createdAt()).isEqualTo(LocalDateTime.parse("2025-01-01T19:04:05.123456"));
        assertThat(row.expiresAt()).isEqualTo(LocalDateTime.parse("2025-01-01T19:14:05.123456"));
        assertThat(row.decidedAt()).isEqualTo(LocalDateTime.parse("2025-01-01T19:05:00.654321"));assertThat(row.resultJson()).isNull();
        var unknown=store.find(901,"uncertain",false);assertThat(unknown.digest()).isEqualTo("B".repeat(64));assertThat(unknown.resultJson()).isEqualTo("null");assertThat(unknown.status()).isEqualTo("NEEDS_REVIEW");
        assertThat(store.find(901,"completed",false).resultJson()).isEqualTo(source.queryForObject("SELECT CAST(result_json AS CHAR) FROM agent_pending_action WHERE action_id='completed'",String.class));
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE updated_at IS NOT NULL OR finished_at IS NOT NULL",Integer.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE request_id='shared-action'",Integer.class)).isEqualTo(2);
        var chat=target.queryForMap("SELECT * FROM workflow_instance WHERE kind='LEGACY_CHAT_ACTION' AND legacy_key=?",Long.toString(LARGE_ID));
        assertThat(chat.get("workflow_id")).isEqualTo("legacy-chat-action:"+LARGE_ID);assertThat(chat.get("chat_action_session_id")).isEqualTo("Session-Original");
        assertThat(chat.get("created_at")).isNull();assertThat(chat.get("actor_user_id")).isNull();
        var evidence=json.readTree((String)chat.get("payload_json"));assertThat(evidence.path("actionPayload").asText()).isEqualTo(RAW);
        assertThat(evidence.path("legacySessionId").asText()).isEqualTo("session-original");assertThat(evidence.path("legacyCreatedAt").isNull()).isTrue();assertThat(evidence.path("legacyId").asText()).isEqualTo(Long.toString(LARGE_ID));
        assertThat(evidence.path("errorMessage").asText()).isEqualTo("原始错误  ");
        assertThat(store.audits(902,"deleted-action")).hasSize(1);assertThat(store.audits(901,"shared-action").get(0).id()).isGreaterThan(700);
        var audit=json.readTree(target.queryForObject("SELECT payload_json FROM audit_event WHERE legacy_key=?",String.class,Long.toString(LARGE_ID)));
        assertThat(audit.path("legacyId").asText()).isEqualTo(Long.toString(LARGE_ID));assertThat(audit.path("actorRole").asText()).isEqualTo("SUPERVISOR");
        assertThat(target.queryForObject("SELECT COUNT(*) FROM agent_run",Integer.class)).isZero();assertThat(snapshot()).isEqualTo(original);assertThat(sequences()).isEqualTo(sequences);
    }

    @ParameterizedTest @CsvSource({"+00:00,2025-01-02 03:04:05.123456","-05:30,2025-01-02 08:34:05.123456"})
    void usesObservedOffsetAndPreservesFractionalPrecision(String offset,String expected)throws Exception{
        var before=snapshot();fixture.migrate(offset);
        assertThat(target.queryForObject("SELECT CAST(created_at AS CHAR) FROM workflow_instance WHERE workflow_id='agent-action:shared-action'",String.class)).isEqualTo(expected);
        assertThat(snapshot()).isEqualTo(before);
    }

    @Test void readsFullLengthSupplementaryUnicodeUsingMysqlCharacterLimits()throws Exception{
        String scalar=new String(Character.toChars(0x10437)),full64=scalar.repeat(64),full160=scalar.repeat(160);
        source.update("UPDATE agent_pending_action SET call_id=?,resource_version=?,policy_version=? WHERE action_id='shared-action'",full160,full64,full64);
        var before=snapshot();fixture.migrate("+08:00");
        var row=new AgentActionPersistence(target,new ObjectMapper()).find(901,"shared-action",false);
        assertThat(row.proposal().callId()).isEqualTo(full160);assertThat(row.proposal().resourceVersion()).isEqualTo(full64);assertThat(row.proposal().policyVersion()).isEqualTo(full64);
        assertThat(target.queryForObject("SELECT agent_action_call_id FROM workflow_instance WHERE workflow_id='agent-action:shared-action'",String.class)).isEqualTo(full160);
        assertThat(snapshot()).isEqualTo(before);
    }

    @ParameterizedTest @ValueSource(strings={
            "ALTER TABLE agent_pending_action ADD COLUMN unknown_fact TEXT NULL",
            "ALTER TABLE agent_pending_action MODIFY COLUMN call_id VARCHAR(160) COLLATE utf8mb4_unicode_ci NULL",
            "ALTER TABLE agent_pending_action MODIFY COLUMN version BIGINT NOT NULL DEFAULT 2",
            "ALTER TABLE agent_pending_action DROP INDEX uk_action_request",
            "ALTER TABLE agent_pending_action ADD UNIQUE KEY unexpected_unique(action_id,user_id)",
            "ALTER TABLE agent_action_audit MODIFY COLUMN id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT",
            "ALTER TABLE agent_action_audit ADD CONSTRAINT unexpected_check CHECK(user_id>0)",
            "ALTER TABLE chat_pending_action DROP FOREIGN KEY fk_chat_pending_session",
            "ALTER TABLE chat_pending_action ALTER COLUMN status SET DEFAULT 'pending'",
            "ALTER TABLE chat_pending_action MODIFY COLUMN created_at DATETIME(6) NULL DEFAULT CURRENT_TIMESTAMP(6)",
            "CREATE TRIGGER unexpected_source_trigger BEFORE INSERT ON agent_pending_action FOR EACH ROW SET NEW.reason_code='changed'"})
    void rejectsUnreviewedSourceStructureWithoutWritingEitherSchema(String change)throws Exception{
        source.execute(change);rejectAndAssertUnchanged();
    }

    @ParameterizedTest @ValueSource(strings={
            "UPDATE agent_pending_action SET user_id=0 WHERE action_id='shared-action'",
            "UPDATE agent_pending_action SET arguments_digest='invalid' WHERE action_id='shared-action'",
            "UPDATE agent_pending_action SET operation='UNKNOWN_TOOL' WHERE action_id='shared-action'",
            "UPDATE agent_pending_action SET status='unrecognized' WHERE action_id='shared-action'",
            "UPDATE agent_pending_action SET created_at='9999-01-01 00:00:00' WHERE action_id='shared-action'",
            "UPDATE agent_action_audit SET occurred_at='9999-01-01 00:00:00' WHERE id=91",
            "UPDATE chat_pending_action SET confirmed_at='9999-01-01 00:00:00' WHERE id=2",
            "UPDATE agent_action_audit SET user_id=0 WHERE id=91"})
    void rejectsInvalidRowsAndOutOfRangeUtcConversionInsteadOfDroppingHistory(String change)throws Exception{
        source.update(change);rejectAndAssertUnchanged();
    }

    @ParameterizedTest @ValueSource(strings={
            "CREATE TRIGGER corrupt_workflow BEFORE INSERT ON workflow_instance FOR EACH ROW SET NEW.fence=99",
            "CREATE TRIGGER corrupt_workflow BEFORE INSERT ON workflow_instance FOR EACH ROW SET NEW.payload_json=JSON_REMOVE(NEW.payload_json,'$.legacyExpiresAt')",
            "CREATE TRIGGER corrupt_workflow BEFORE INSERT ON workflow_instance FOR EACH ROW SET NEW.actor_user_id=987",
            "CREATE TRIGGER corrupt_workflow BEFORE INSERT ON workflow_instance FOR EACH ROW SET NEW.legacy_key=CONCAT(NEW.legacy_key,' ')",
            "CREATE TRIGGER corrupt_audit BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.quantity=3,NEW.unit='BYTES'",
            "CREATE TRIGGER corrupt_audit BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.payload_json=JSON_REMOVE(NEW.payload_json,'$.reasonCode')",
            "CREATE TRIGGER corrupt_audit BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.legacy_source=CONCAT(NEW.legacy_source,' ')",
            "CREATE TRIGGER corrupt_audit BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.policy_version=CONCAT(NEW.policy_version,' ')",
            "CREATE TRIGGER corrupt_previous_workflow BEFORE INSERT ON audit_event FOR EACH ROW UPDATE workflow_instance SET fence=77 WHERE kind='AGENT_ACTION'"})
    void exactTailComparisonRollsBackAllThreeCopiesDespiteUnchangedRowCounts(String trigger)throws Exception{
        fixture.installTarget(trigger+";");rejectAndAssertUnchanged();
    }

    @Test void requiresExactPreviouslyMigratedParentIdentity()throws Exception{
        target.update("UPDATE chat_session SET session_id='another-key'");rejectAndAssertUnchanged();
    }
    @Test void importedChatKeepsOldUniqueCollationAndDoubleCascadeWithoutChangingAgentAction()throws Exception{
        fixture.migrate("+08:00");
        assertThatThrownBy(()->target.update("UPDATE workflow_instance SET request_id='resume',resource_id='resume' WHERE kind='LEGACY_CHAT_ACTION' AND legacy_key=?",Long.toString(LARGE_ID))).isInstanceOf(org.springframework.dao.DataAccessException.class);
        target.update("UPDATE chat_session SET session_id='renamed-session'");
        assertThat(target.queryForList("SELECT chat_action_session_id FROM workflow_instance WHERE kind='LEGACY_CHAT_ACTION'",String.class)).containsOnly("renamed-session");
        target.update("DELETE FROM chat_session");
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='LEGACY_CHAT_ACTION'",Integer.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='AGENT_ACTION'",Integer.class)).isEqualTo(3);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='AGENT_ACTION'",Integer.class)).isEqualTo(2);
        assertThat(source.queryForObject("SELECT COUNT(*) FROM chat_pending_action",Integer.class)).isEqualTo(2);
    }
    @Test void refusesASecondImportWithoutDeletingTheFirstResult()throws Exception{
        fixture.migrate("+08:00");var before=target.queryForList("SELECT * FROM workflow_instance ORDER BY id");
        assertThatThrownBy(()->fixture.migrate("+08:00")).isInstanceOf(Exception.class);
        assertThat(target.queryForList("SELECT * FROM workflow_instance ORDER BY id")).isEqualTo(before);
    }
    private void rejectAndAssertUnchanged()throws Exception{
        var before=snapshot();var sequences=sequences();
        assertThatThrownBy(()->fixture.migrate("+08:00")).isInstanceOf(Exception.class);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance",Integer.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event",Integer.class)).isEqualTo(1);
        assertThat(snapshot()).isEqualTo(before);assertThat(sequences()).isEqualTo(sequences);
    }
    private List<List<Map<String,Object>>> snapshot(){return List.of(source.queryForList("SELECT * FROM agent_pending_action ORDER BY action_id"),source.queryForList("SELECT * FROM agent_action_audit ORDER BY id"),source.queryForList("SELECT * FROM chat_pending_action ORDER BY id"));}
    private List<Map<String,Object>> sequences(){return source.queryForList("SELECT table_name,auto_increment FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('agent_action_audit','chat_pending_action') ORDER BY table_name");}
}
