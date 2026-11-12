package com.ruanzhu.doorhandle.module.ai.mcp;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.ai.testsupport.CompactMcpMySqlFixture;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.jdbc.core.JdbcTemplate;
import static org.assertj.core.api.Assertions.*;

/** Thirteen original sources and complete 29-table target, only on bound disposable ECS schemas. */
@EnabledIfSystemProperty(named="doorhandle.mcp.source.config",matches=".+")
class McpMigrationMySqlTest {
    private CompactMcpMySqlFixture fixture;
    private JdbcTemplate source,target;
    private final ObjectMapper json=new ObjectMapper();
    private static final long LARGE=9_007_199_254_740_993L;
    private static final String INSTALL="22222222-2222-2222-2222-222222222222";
    private static final String EXEC="11111111-1111-1111-1111-111111111111";
    private static final String REQUEST="33333333-3333-3333-3333-333333333333";
    private static final String IMAGE="sha256:"+"e".repeat(64);
    private static final List<String> TABLES=List.of("agent_local_mcp","agent_local_mcp_audit","agent_mcp_install_job","agent_mcp_execution","agent_mcp_execution_command","agent_fetch_installation","agent_fetch_lifecycle_command","agent_mcp_install_worker","agent_fetch_image","agent_fetch_image_command","agent_fetch_image_retention","agent_fetch_image_retention_control","agent_fetch_image_retention_event");

    @BeforeEach void setup()throws Exception{
        fixture=new CompactMcpMySqlFixture("doorhandle.mcp.mysql.config","doorhandle_agent_verify_","ecsit_",true);
        source=fixture.source();target=fixture.jdbc();
        source.update("INSERT INTO agent_local_mcp(id,owner_user_id,server_key,package_version,status,enabled,revision,operation_id,request_id,lease_expires_at,manifest_json,manifest_sha256,error_code,created_at,updated_at) VALUES(?,901,'fetch','legacy-version','CANCELLED',FALSE,7,'old-operation',NULL,NULL,CAST(? AS JSON),?,'UNRESOLVED','2025-01-02 03:04:05','2025-01-02 03:05:06')",LARGE,"{\"raw\":\"原内容  \",\"optional\":null}","a".repeat(64));
        source.update("INSERT INTO agent_local_mcp_audit(id,owner_user_id,server_key,action_name,outcome,revision,operation_id,run_id,call_id,detail_json,created_at) VALUES(?,901,'fetch','INSTALL','UNKNOWN',7,NULL,NULL,NULL,CAST(? AS JSON),'2025-01-02 03:04:05')",LARGE,"{\"exitVerified\":false,\"detail\":null}");
        source.update("INSERT INTO agent_mcp_install_job(id,operation_id,owner_user_id,owner_username,runtime_sha256,status,worker_token,created_at,updated_at) VALUES(?,'old-job',901,'deleted-account',?,'RUNNING','original-token','2025-01-02 03:04:05','2025-01-02 03:05:06')",LARGE,"a".repeat(64));
        source.update("INSERT INTO agent_mcp_execution(id,execution_id,owner_user_id,installation_id,runtime_sha256,pool_id,purpose,state,revision,exit_verified,cleanup_confirmed,run_id,call_id,lease_expires_at,created_at,updated_at,transport,image_id) VALUES(?,?,901,?,?,?,'CALL','NEEDS_REVIEW',9,FALSE,FALSE,NULL,NULL,'2025-01-02 03:14:05.123456','2025-01-02 03:04:05.123456','2025-01-02 03:05:06.654321','STDIO',NULL)",LARGE,EXEC,INSTALL,"a".repeat(64),"b".repeat(32));
        for(long owner:List.of(901L,902L)){
            source.update("INSERT INTO agent_mcp_execution_command(owner_user_id,request_id,execution_id,request_sha256,status) VALUES(?,'shared-request',?,?,'NEEDS_REVIEW')",owner,EXEC,"c".repeat(64));
            source.update("INSERT INTO agent_fetch_installation(owner_user_id,installation_id,prior_installation_id,state,revision,writer_exit_verified,retained_for_rollback,package_version,transport,image_id,manifest_json,manifest_sha256,cleanup_request,cleanup_expires_at,created_at,updated_at,reconcile_request,reconcile_expires_at,writer_evidence_code,reserved_bytes) VALUES(?,?,NULL,'NEEDS_REVIEW',4,FALSE,TRUE,'legacy-version','STDIO',NULL,NULL,NULL,NULL,NULL,'2025-01-02 03:04:05.123456','2025-01-02 03:05:06.654321',NULL,NULL,'UNRESOLVED',2097152)",owner,INSTALL);
            source.update("INSERT INTO agent_fetch_lifecycle_command(owner_user_id,request_id,installation_id,action_name,request_sha256,status) VALUES(?,'shared-request',?,'RECONCILE',?,'NEEDS_REVIEW')",owner,INSTALL,"c".repeat(64));
            source.update("INSERT INTO agent_mcp_install_worker(owner_user_id,installation_id,node_sha256,runtime_sha256,controller_pid,controller_started,container_id,container_started,controller_pool_id,state,revision,writer_transport,native_pool_id) VALUES(?,?,?,?,12345,'2025-01-02T03:04:05Z',NULL,NULL,NULL,'RUNNING',4,'STDIO',?)",owner,INSTALL,"d".repeat(64),"a".repeat(64),"b".repeat(32));
            source.update("INSERT INTO agent_fetch_image_command(owner_user_id,request_id,image_id,request_sha256,action_name,state,retention_protocol) VALUES(?,?,?,?,'RETIRE','NEEDS_REVIEW',3)",owner,REQUEST,IMAGE,"f".repeat(64));
        }
        source.update("INSERT INTO agent_fetch_image(image_id,state,revision,cleanup_request,cleanup_owner_user_id,runner_pool_id,archive_sha256,image_absent,updated_at) VALUES(?,'NEEDS_REVIEW',11,?,NULL,NULL,NULL,FALSE,'2025-01-02 03:04:05.123456')",IMAGE,REQUEST);
        source.update("INSERT INTO agent_fetch_image_retention(reference_id,image_id,reference_kind,state,updated_at) VALUES('old-release',?,'DEPLOYMENT','HELD','2025-01-02 03:04:05.123456'),('orphan-reference',?,'RECOVERY','HELD','2025-01-02 03:04:05.000001')",IMAGE,"sha256:"+"f".repeat(64));
        source.update("UPDATE agent_fetch_image_retention_control SET state='ACTIVE',revision=7,updated_at='2025-01-02 03:04:05.123456' WHERE control_id=1");
        // Original nullable unique key permits both facts; NULL image is not fabricated into a fake image.
        source.update("INSERT INTO agent_fetch_image_retention_event(request_id,action_name,image_id,created_at) VALUES(?,'RELEASE',NULL,'2025-01-02 03:04:05.123456'),(?,'RELEASE',NULL,'2025-01-02 03:04:05.000001')","a".repeat(32),"a".repeat(32));
    }
    @AfterEach void close()throws Exception{if(fixture!=null)fixture.close();}

    @Test void legacyConnectorSourceKeyGuardsAllowGeneratedIdsAndRollbackMismatchedInsertAndRekey()throws Exception{
        com.ruanzhu.doorhandle.module.ai.testsupport.CompactBaselineParts.installClockGuards(target,"db/compact/009-agent-connector-clock-guards.sql","agent_connector");
        long owner=java.util.concurrent.ThreadLocalRandom.current().nextLong(1_000_000,1_000_000_000);
        String normal="normal-"+java.util.UUID.randomUUID().toString().substring(0,20);
        target.update("INSERT INTO agent_connector(owner_user_id,server_key,package_version,created_at,updated_at) VALUES(?,?,'fixture',UTC_TIMESTAMP(),UTC_TIMESTAMP())",owner,normal);
        assertThat(target.queryForObject("SELECT id FROM agent_connector WHERE owner_user_id=? AND server_key=?",Long.class,owner,normal)).isPositive();
        long sourceId=java.util.concurrent.ThreadLocalRandom.current().nextLong(2_000_000_000_000L,3_000_000_000_000L);
        var wall=new java.util.LinkedHashMap<String,Object>();wall.put("lease_expires_at",null);
        wall.put("created_at","2020-01-02 00:00:00");wall.put("updated_at","2020-01-02 00:00:01");
        String evidence=json.writeValueAsString(Map.of("protocol","doorhandle-legacy-clock-v1","status","UNRESOLVED",
            "sourceTable","agent_local_mcp","sourceKey",Map.of("id",sourceId),"sourceSnapshotSha256","a".repeat(64),
            "sourceRowSha256","b".repeat(64),"sourceWallTimes",wall));
        String insert="INSERT INTO agent_connector(id,owner_user_id,server_key,package_version,legacy_clock_json) VALUES(?,?,?,'fixture',?)";
        String valid="valid-"+java.util.UUID.randomUUID().toString().substring(0,20);
        target.update(insert,sourceId,owner,valid,evidence);
        String invalid="invalid-"+java.util.UUID.randomUUID().toString().substring(0,20);
        assertThatThrownBy(()->target.update(insert,sourceId+1,owner,invalid,evidence))
            .isInstanceOf(org.springframework.dao.DataAccessException.class).hasStackTraceContaining("Original legacy source key does not match target row");
        assertThat(target.queryForObject("SELECT COUNT(*) FROM agent_connector WHERE owner_user_id=? AND server_key=?",Integer.class,owner,invalid)).isZero();
        assertThatThrownBy(()->target.update("UPDATE agent_connector SET id=? WHERE id=?",sourceId+1,sourceId))
            .isInstanceOf(org.springframework.dao.DataAccessException.class).hasStackTraceContaining("Original legacy source key does not match target row");
        assertThat(target.queryForObject("SELECT id FROM agent_connector WHERE owner_user_id=? AND server_key=?",Long.class,owner,valid)).isEqualTo(sourceId);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM agent_connector WHERE id=?",Integer.class,sourceId+1)).isZero();
    }

    @Test void preservesAllOneHundredFortyFieldsOwnerScopedIdentitiesOrphansAndUnknownExitEvidence()throws Exception{
        var before=snapshot();var seq=sequences();fixture.migrate("+08:00");
        assertThat(target.queryForObject("SELECT COUNT(*) FROM users",Integer.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance",Integer.class)).isEqualTo(12);
        var execution=target.queryForMap("SELECT * FROM workflow_instance WHERE kind='MCP_EXECUTION'");
        assertThat(execution.get("status")).isEqualTo("NEEDS_REVIEW");assertThat(execution.get("mcp_exit_verified")).isEqualTo(false);
        assertThat(execution.get("mcp_cleanup_confirmed")).isEqualTo(false);assertThat(execution.get("claim_token")).isNull();
        assertThat(execution.get("legacy_key")).isEqualTo(Long.toString(LARGE));
        assertThat(target.queryForObject("SELECT CAST(lease_expires_at AS CHAR) FROM workflow_instance WHERE kind='MCP_EXECUTION'",String.class)).isEqualTo("2025-01-01 19:14:05.123456");
        assertThat(target.queryForObject("SELECT CAST(mcp_source_created_at AS CHAR) FROM workflow_instance WHERE kind='MCP_EXECUTION'",String.class)).isEqualTo("2025-01-02 03:04:05.123456");
        assertThat(target.queryForObject("SELECT mcp_source_utc_offset FROM workflow_instance WHERE kind='MCP_EXECUTION'",String.class)).isEqualTo("+08:00");
        for(String kind:List.of("MCP_EXECUTION_COMMAND","MCP_INSTALLATION","MCP_LIFECYCLE_COMMAND","MCP_INSTALL_WORKER","MCP_IMAGE_COMMAND")){
            assertThat(target.queryForObject("SELECT COUNT(DISTINCT owner_user_id) FROM workflow_instance WHERE kind=?",Integer.class,kind)).isEqualTo(2);
            assertThat(target.queryForList("SELECT idempotency_scope FROM workflow_instance WHERE kind=?",String.class,kind)).containsExactlyInAnyOrder(kind+":OWNER:901",kind+":OWNER:902");
        }
        assertThat(target.queryForObject("SELECT mcp_worker_token FROM workflow_instance WHERE kind='MCP_INSTALL_JOB'",String.class)).isEqualTo("original-token");
        assertThat(target.queryForList("SELECT reserved_bytes FROM workflow_instance WHERE kind='MCP_INSTALLATION' ORDER BY owner_user_id",Long.class)).containsExactly(2097152L,2097152L);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='MCP_INSTALL_WORKER' AND mcp_container_id IS NULL AND mcp_transport='STDIO' AND mcp_controller_started='2025-01-02T03:04:05Z'",Integer.class)).isEqualTo(2);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM content_asset WHERE asset_kind='CONNECTOR_IMAGE' AND created_at IS NULL AND lifecycle='NEEDS_REVIEW'",Integer.class)).isEqualTo(1);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM content_link WHERE link_kind='CONNECTOR_RETENTION' AND created_at IS NULL",Integer.class)).isEqualTo(2);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='MCP_RETENTION' AND resource_id IS NULL",Integer.class)).isEqualTo(2);
        assertThat(target.queryForObject("SELECT state_code FROM runtime_state WHERE namespace='MCP_RETENTION_CONTROL' AND scope_key='1'",String.class)).isEqualTo("ACTIVE");
        var clocks=target.queryForList("SELECT payload_json FROM audit_event WHERE kind='MCP_MIGRATION_CLOCK'",String.class);
        assertThat(clocks).hasSize(13);for(String clock:clocks){var row=json.readTree(clock);assertThat(row.size()).isEqualTo(4);assertThat(row.path("sourceUtcOffset").asText()).isEqualTo("+08:00");assertThat(row.path("sourceSnapshotSha256").asText()).matches("[a-f0-9]{64}");}
        assertThat(snapshot()).isEqualTo(before);assertThat(sequences()).isEqualTo(seq);
        assertThat(target.queryForObject("SELECT AUTO_INCREMENT FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='agent_connector'",Long.class)).isEqualTo(((Number)seq.stream().filter(x->x.get("table_name").equals("agent_local_mcp")).findFirst().orElseThrow().get("auto_increment")).longValue());
    }

    @Test void installationReservationsStaySeparateFromSkillExecutionFields()throws Exception{
        var before=snapshot();fixture.migrate("+08:00");
        var installation=target.queryForMap("SELECT * FROM workflow_instance WHERE kind='MCP_INSTALLATION' AND owner_user_id=901");
        assertThat(installation.get("reserved_bytes")).isEqualTo(2097152L);
        for(String column:List.of("execution_state","exit_verified","execution_deadline"))assertThat(installation.get(column)).isNull();
        for(String assignment:List.of("execution_state='RUNNING'","exit_verified=FALSE","execution_deadline=UTC_TIMESTAMP(6)","reserved_bytes=NULL"))
            assertThatThrownBy(()->target.update("UPDATE workflow_instance SET "+assignment+" WHERE kind='MCP_INSTALLATION' AND owner_user_id=901"))
                .rootCause().isInstanceOfSatisfying(java.sql.SQLException.class,error->assertThat(error.getErrorCode()).isEqualTo(3819));
        assertThatThrownBy(()->target.update("UPDATE workflow_instance SET reserved_bytes=2097152 WHERE kind='MCP_INSTALL_JOB'"))
            .rootCause().isInstanceOfSatisfying(java.sql.SQLException.class,error->assertThat(error.getErrorCode()).isEqualTo(3819));
        assertThat(target.queryForMap("SELECT * FROM workflow_instance WHERE kind='MCP_INSTALLATION' AND owner_user_id=901")).isEqualTo(installation);
        assertThat(target.queryForObject("SELECT reserved_bytes FROM workflow_instance WHERE kind='MCP_INSTALL_JOB'",Long.class)).isNull();
        assertThat(snapshot()).isEqualTo(before);
    }

    @ParameterizedTest @ValueSource(strings={
        "ALTER TABLE agent_mcp_execution ADD COLUMN unreviewed_field TEXT NULL",
        "ALTER TABLE agent_mcp_execution DROP INDEX idx_mcp_execution_expiry",
        "ALTER TABLE agent_mcp_install_job MODIFY worker_token VARCHAR(64) COLLATE utf8mb4_unicode_ci NULL",
        "ALTER TABLE agent_fetch_image_command ALTER retention_protocol SET DEFAULT 2",
        "CREATE TRIGGER source_mcp_mutation BEFORE INSERT ON agent_local_mcp_audit FOR EACH ROW SET NEW.outcome='changed'"})
    void rejectsUnreviewedSourceShapeBeforeCopy(String change)throws Exception{source.execute(change);reject();}

    @ParameterizedTest @ValueSource(strings={
        "UPDATE agent_mcp_execution SET lease_expires_at='9999-01-01 00:00:00'",
        "UPDATE agent_fetch_image SET updated_at='9999-01-01 00:00:00'",
        "UPDATE agent_mcp_execution SET state='UNREGISTERED'",
        "UPDATE agent_mcp_execution SET cleanup_confirmed=TRUE,exit_verified=FALSE"})
    void stopsOnUnrepresentableClockOrUnsafeStateWithoutRewritingOriginal(String change)throws Exception{source.update(change);reject();}

    @ParameterizedTest @ValueSource(strings={
        "CREATE TRIGGER corrupt_mcp BEFORE INSERT ON workflow_instance FOR EACH ROW SET NEW.mcp_native_pool_id=REPEAT('e',32)",
        "CREATE TRIGGER corrupt_mcp BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.quantity=3,NEW.unit='BYTES'",
        "CREATE TRIGGER corrupt_mcp BEFORE INSERT ON audit_event FOR EACH ROW UPDATE agent_connector SET enabled=TRUE",
        "CREATE TRIGGER corrupt_mcp BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.payload_json=IF(NEW.kind='MCP_MIGRATION_CLOCK',JSON_SET(NEW.payload_json,'$.sourceUtcOffset','+00:00'),NEW.payload_json)",
        "CREATE TRIGGER corrupt_mcp BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.occurred_at=IF(NEW.kind='MCP',DATE_ADD(NEW.occurred_at,INTERVAL 1 MICROSECOND),NEW.occurred_at)",
        "CREATE TRIGGER corrupt_mcp BEFORE INSERT ON workflow_instance FOR EACH ROW SET NEW.mcp_source_created_at=DATE_ADD(NEW.mcp_source_created_at,INTERVAL 1 MICROSECOND)",
        "CREATE TRIGGER corrupt_mcp BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.occurred_at=IF(NEW.kind='MCP_MIGRATION_CLOCK',DATE_ADD(NEW.occurred_at,INTERVAL 1 MICROSECOND),NEW.occurred_at)"})
    void fullTailComparisonRollsBackEarlierInsertionsAndClockEvidence(String trigger)throws Exception{fixture.installTarget(trigger+";");reject();}

    @Test void refusesSecondCopyAndKeepsFirstCommittedCandidate()throws Exception{
        fixture.migrate("+08:00");var workflows=target.queryForList("SELECT * FROM workflow_instance ORDER BY id");
        assertThatThrownBy(()->fixture.migrate("+08:00")).isInstanceOf(Exception.class);
        assertThat(target.queryForList("SELECT * FROM workflow_instance ORDER BY id")).isEqualTo(workflows);
    }
    private Map<String,List<Map<String,Object>>> snapshot(){
        var result=new java.util.LinkedHashMap<String,List<Map<String,Object>>>();
        for(String table:TABLES){String order=table.equals("agent_fetch_image")?"image_id":table.equals("agent_fetch_image_retention")?"reference_id,image_id":table.equals("agent_fetch_image_retention_control")?"control_id":"id";result.put(table,source.queryForList("SELECT * FROM "+table+" ORDER BY "+order));}return result;
    }
    private List<Map<String,Object>> sequences(){return source.queryForList("SELECT table_name,auto_increment FROM information_schema.tables WHERE table_schema=DATABASE() ORDER BY table_name");}
    private void reject()throws Exception{
        var before=snapshot();var seq=sequences();assertThatThrownBy(()->fixture.migrate("+08:00")).isInstanceOf(Exception.class);
        assertThat(snapshot()).isEqualTo(before);assertThat(sequences()).isEqualTo(seq);
        for(String table:List.of("agent_connector","workflow_instance","content_asset","content_link","runtime_state","audit_event"))assertThat(target.queryForObject("SELECT COUNT(*) FROM "+table,Integer.class)).isZero();
    }
}
