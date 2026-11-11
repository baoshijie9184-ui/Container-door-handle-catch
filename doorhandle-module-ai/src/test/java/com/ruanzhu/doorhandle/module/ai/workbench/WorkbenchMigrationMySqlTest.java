package com.ruanzhu.doorhandle.module.ai.workbench;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.ai.EcsIsolatedMysql;
import com.ruanzhu.doorhandle.module.ai.testsupport.CompactActionMySqlFixture;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import static org.assertj.core.api.Assertions.*;

/** Real V37 source and complete compact target. No local database or H2 variant. */
@EnabledIfSystemProperty(named="workbench.migration.target",matches=".+")
@Timeout(120)
class WorkbenchMigrationMySqlTest {
    private final ObjectMapper json=new ObjectMapper();
    private CompactActionMySqlFixture target;
    private org.springframework.jdbc.datasource.DriverManagerDataSource sourceData;
    private JdbcTemplate source,jdbc;
    private WorkbenchLegacyMigration migration;
    private WorkbenchLegacyMigration.Admission admission;
    private static final Set<String> SOURCE_TABLES=Set.of("agent_workbench_item","agent_workbench_request","agent_workbench_audit");
    private String sourceSchema;
    @BeforeEach void create()throws Exception{
        target=new CompactActionMySqlFixture("workbench.migration.target","doorhandle_wb_verify_","wb_verify_",false);jdbc=target.jdbc();
        sourceData=EcsIsolatedMysql.open(System.getProperty("workbench.migration.source"),"doorhandle_agent_verify_");source=new JdbcTemplate(sourceData);
        if(source.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()",Integer.class)!=0)throw new SecurityException("Workbench source fixture must be empty");
        sourceSchema=source.queryForObject("SELECT DATABASE()",String.class);String targetSchema=jdbc.queryForObject("SELECT DATABASE()",String.class);
        String uuid=jdbc.queryForObject("SELECT @@server_uuid",String.class);
        if(sourceSchema.equals(targetSchema)||!uuid.equals(source.queryForObject("SELECT @@server_uuid",String.class)))throw new SecurityException("Distinct same-server schemas required");
        String ddl=Files.readString(Path.of("../sql/mysql/migration-V37-agent-workbench.sql")).replaceAll("(?m)^--.*$","");
        for(String statement:ddl.split(";"))if(statement.matches("(?s).*CREATE TABLE IF NOT EXISTS agent_workbench_(item|request|audit) \\(.*"))source.execute(statement);
        var collations=new LinkedHashMap<String,String>();for(String table:SOURCE_TABLES)collations.put(table,source.queryForObject("SELECT table_collation FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=?",String.class,table));
        admission=new WorkbenchLegacyMigration.Admission(System.getenv("DOORHANDLE_ECS_INSTANCE_ID"),System.getenv("DOORHANDLE_ECS_MACHINE_ID"),sourceSchema,targetSchema,uuid,ZoneOffset.ofHours(8),collations);
        migration=new WorkbenchLegacyMigration(jdbc,new DataSourceTransactionManager(target.dataSource()),json);
    }
    @AfterEach void close()throws Exception{
        if(source!=null){var tables=new HashSet<>(source.queryForList("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()",String.class));if(!SOURCE_TABLES.containsAll(tables))throw new SecurityException("Unowned source table; preserving fixture");for(String table:tables)source.execute("DROP TABLE `"+table+"`");}
        if(target!=null)target.close();
    }
    private String seed(){
        String payload="{ \"parentId\" : \"deleted-parent\", \"parentTaskId\":\"old-parent-task\", \"logicalTaskId\":\"known-child-task\", \"specialist\":\"detection-task\", \"role\":\"INSPECTOR\", \"question\":\"保留原文\\n第二行\", \"title\":\"旧任务\", \"runId\":\"old-run\" }";
        source.update("INSERT INTO agent_workbench_item(id,item_id,user_id,session_id,kind,status,revision,payload,created_at,updated_at) VALUES(9223372036854775810,'legacy-child',7,'deleted-session','CHILD','RUNNING',9,?,?,?)",payload,LocalDateTime.of(2025,3,4,12,13,14,123456000),LocalDateTime.of(2026,1,2,3,4,5,654321000));
        source.execute("ALTER TABLE agent_workbench_item AUTO_INCREMENT=9223372036854775900");
        source.update("INSERT INTO agent_workbench_request(id,user_id,request_id,request_sha256,result_json) VALUES(21,7,'legacy-command',?,?)",WorkbenchStore.hash("original command signature"),"{ \"modelId\" : \"fixture-model\", \"revision\" : 7 }");
        source.update("INSERT INTO agent_workbench_audit(id,user_id,session_id,item_id,action,revision,payload_sha256,created_at) VALUES(31,7,'deleted-session','missing-item','OLD_OBSERVATION',9,?,?)",WorkbenchStore.hash("original historical payload, not the current item"),LocalDateTime.of(2025,4,5,6,7,8,123000));
        return payload;
    }
    @Test void preservesAllSourceColumnsRawBytesUnknownTimesOrphansAndUnsignedIds(){
        String payload=seed();var receipt=migration.copy(admission);assertThat(migration.verifyCommitted(admission,receipt).matches()).isTrue();
        assertThat(receipt.itemRows()).isEqualTo(1);assertThat(receipt.commandRows()).isEqualTo(1);assertThat(receipt.auditRows()).isEqualTo(1);assertThat(receipt.logicalTaskRows()).isEqualTo(1);
        assertThat(receipt.sources().get("agent_workbench_item").autoIncrement()).isEqualTo("9223372036854775900");
        var store=new WorkbenchStore(jdbc,new DataSourceTransactionManager(target.dataSource()),json);var item=store.require(7,"deleted-session","legacy-child");
        assertThat(item.legacy().payloadJson()).isEqualTo(payload);assertThat(item.revision()).isEqualTo(9);assertThat(item.claimToken()).isNull();assertThat(item.fence()).isZero();assertThat(item.lease()).isNull();
        assertThat(jdbc.queryForObject("SELECT legacy_key FROM workflow_instance WHERE kind='WORKBENCH_CHILD'",String.class)).isEqualTo("9223372036854775810");
        assertThat(jdbc.queryForObject("SELECT created_at FROM workflow_instance WHERE kind='WORKBENCH_CHILD'",LocalDateTime.class)).isEqualTo(LocalDateTime.of(2025,3,4,4,13,14,123456000));
        var command=jdbc.queryForMap("SELECT created_at,updated_at,finished_at FROM workflow_instance WHERE kind='WORKBENCH_COMMAND'");assertThat(command.values()).containsOnlyNulls();
        var task=jdbc.queryForMap("SELECT created_at,updated_at,finished_at,payload_json FROM workflow_instance WHERE kind='WORKBENCH_LOGICAL_TASK'");assertThat(task.get("created_at")).isNull();assertThat(task.get("updated_at")).isNull();assertThat(task.get("finished_at")).isNull();
        assertThat(task.get("payload_json").toString()).contains("\"importedCurrentSnapshot\":true","\"initialRunId\":null");
        assertThat(jdbc.queryForObject("SELECT content_sha256 FROM audit_event WHERE kind='WORKBENCH'",String.class)).isEqualTo(WorkbenchStore.hash("original historical payload, not the current item"));
        var replay=store.request(7,"legacy-command","original command signature",AgentWorkbenchService.ModelSelection.class,()->{throw new AssertionError("Imported command must not execute again");});assertThat(replay).isEqualTo(new AgentWorkbenchService.ModelSelection("fixture-model",7));
        assertThatThrownBy(()->store.request(7,"legacy-command","different signature",AgentWorkbenchService.ModelSelection.class,()->null)).hasMessageContaining("409");
        assertThat(new WorkbenchChildProvenanceReader(store).find(7,"deleted-session","legacy-child")).isPresent();assertThat(new WorkbenchChildProvenanceReader(store).find(8,"deleted-session","legacy-child")).isEmpty();
        store.recover(item);assertThat(store.require(7,"deleted-session","legacy-child").status()).isEqualTo("NEEDS_REVIEW");
        assertThat(source.queryForObject("SELECT status FROM agent_workbench_item",String.class)).isEqualTo("RUNNING");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()",Integer.class)).isEqualTo(29);
    }

    @Test void unresolvedSourceKeepsRunningStatusAndWallEvidenceWithoutRecovery(){
        String original=seed();
        String snapshot=com.ruanzhu.doorhandle.module.ai.testsupport.FixtureSourceSnapshot.capture(source,SOURCE_TABLES);
        var unknown=new WorkbenchLegacyMigration.Admission(admission.instanceId(),admission.machineId(),admission.sourceSchema(),admission.targetSchema(),admission.serverUuid(),null,admission.sourceCollations(),snapshot,Set.of("workbench"));
        var receipt=migration.copy(unknown);assertThat(receipt.sourceUtcOffset()).isNull();assertThat(migration.verifyCommitted(unknown,receipt).matches()).isTrue();
        var store=new WorkbenchStore(jdbc,new DataSourceTransactionManager(target.dataSource()),json);var item=store.require(7,"deleted-session","legacy-child");
        assertThat(item.status()).isEqualTo("RUNNING");assertThat(item.updated()).isNull();assertThat(item.lease()).isNull();
        assertThat(item.legacy().payloadJson()).isEqualTo(original);assertThat(item.legacy().sourceUtcOffset()).isNull();
        assertThat(item.legacyClockEvidence().sourceKey()).containsEntry("id",new java.math.BigInteger("9223372036854775810"));
        assertThat(item.legacyClockEvidence().sourceWallTimes()).containsEntry("created_at","2025-03-04 12:13:14.123456");
        assertThat(store.stale()).isEmpty();store.recover(item);assertThat(store.require(7,"deleted-session","legacy-child").status()).isEqualTo("RUNNING");
        assertThatThrownBy(()->store.update(item,"NEEDS_REVIEW",item.data(),"PROCESS_INTERRUPTED")).hasMessageContaining("历史");
        assertThat(store.view(item).data()).containsEntry("clockStatus","UNRESOLVED");
        assertThat(jdbc.queryForObject("SELECT occurred_at FROM audit_event WHERE kind='WORKBENCH'",LocalDateTime.class)).isNull();
    }
    @Test void unresolvedReadyAndQueuedSourcesRemainReadableButNeverEnterDispatch()throws Exception{
        seed();source.update("UPDATE agent_workbench_item SET status='QUEUED' WHERE item_id='legacy-child'");
        source.update("INSERT INTO agent_workbench_item(id,item_id,user_id,session_id,kind,status,revision,payload,created_at,updated_at) VALUES(22,'legacy-ready',7,'deleted-session','EXECUTION','READY',3,?,?,?)",
            "{ \"username\" : \"fixture-user\", \"role\" : \"INSPECTOR\", \"logicalTaskId\" : \"legacy-main-task\", \"continuation\" : \"preserve original continuation\" }",
            LocalDateTime.of(2025,3,4,12,13,14),LocalDateTime.of(2026,1,2,3,4,5));
        String snapshot=com.ruanzhu.doorhandle.module.ai.testsupport.FixtureSourceSnapshot.capture(source,SOURCE_TABLES);
        var unknown=new WorkbenchLegacyMigration.Admission(admission.instanceId(),admission.machineId(),admission.sourceSchema(),admission.targetSchema(),admission.serverUuid(),null,admission.sourceCollations(),snapshot,Set.of("workbench"));
        var receipt=migration.copy(unknown);assertThat(migration.verifyCommitted(unknown,receipt).matches()).isTrue();
        var store=new WorkbenchStore(jdbc,new DataSourceTransactionManager(target.dataSource()),json);
        assertThat(store.require(7,"deleted-session","legacy-ready").status()).isEqualTo("READY");
        assertThat(store.require(7,"deleted-session","legacy-child").status()).isEqualTo("QUEUED");
        assertThat(store.dispatch(0)).isEmpty();
        var confirmed=store.create(7,"deleted-session","confirmed-ready","EXECUTION","READY",
            Map.of("username","fixture-user","role","INSPECTOR","logicalTaskId","confirmed-task","continuation","confirmed continuation"));
        assertThat(store.dispatch(0)).extracting(WorkbenchStore.Row::id).containsExactly(confirmed.id());
        assertThat(store.require(7,"deleted-session","legacy-ready").legacyClockEvidence().sourceSnapshotSha256()).isEqualTo(snapshot);
        assertThat(com.ruanzhu.doorhandle.module.ai.testsupport.FixtureSourceSnapshot.capture(source,SOURCE_TABLES)).isEqualTo(snapshot);
    }
    @Test void clockProvenanceAndPayloadVersionCannotBeMismatched()throws Exception{
        seed();
        String snapshot=com.ruanzhu.doorhandle.module.ai.testsupport.FixtureSourceSnapshot.capture(source,SOURCE_TABLES);
        var unknown=new WorkbenchLegacyMigration.Admission(admission.instanceId(),admission.machineId(),admission.sourceSchema(),admission.targetSchema(),admission.serverUuid(),null,admission.sourceCollations(),snapshot,Set.of("workbench"));
        var receipt=migration.copy(unknown);
        String original=jdbc.queryForObject("SELECT payload_json FROM workflow_instance WHERE kind='WORKBENCH_CHILD'",String.class);
        assertThat(json.readTree(original).path("schemaVersion").intValue()).isEqualTo(2);
        for(int version:List.of(1,3))assertThatThrownBy(()->jdbc.update("UPDATE workflow_instance SET payload_json=JSON_SET(payload_json,'$.schemaVersion',?) WHERE kind='WORKBENCH_CHILD'",version))
            .rootCause().isInstanceOfSatisfying(java.sql.SQLException.class,error->assertThat(error.getErrorCode()).isEqualTo(3819));
        assertThat(jdbc.queryForObject("SELECT payload_json FROM workflow_instance WHERE kind='WORKBENCH_CHILD'",String.class)).isEqualTo(original);
        assertThat(migration.verifyCommitted(unknown,receipt).matches()).isTrue();
        var store=new WorkbenchStore(jdbc,new DataSourceTransactionManager(target.dataSource()),json);
        var current=store.create(7,"deleted-session","current-ready","EXECUTION","READY",Map.of("username","fixture-user","role","INSPECTOR","logicalTaskId","current-task","continuation","current continuation"));
        assertThatThrownBy(()->jdbc.update("UPDATE workflow_instance SET payload_json=JSON_SET(payload_json,'$.schemaVersion',2) WHERE resource_type='WORKBENCH_ITEM' AND resource_id=?",current.id()))
            .rootCause().isInstanceOfSatisfying(java.sql.SQLException.class,error->assertThat(error.getErrorCode()).isEqualTo(3819));
        assertThat(store.require(7,"deleted-session",current.id()).legacyClockEvidence()).isNull();
        assertThat(store.dispatch(0)).extracting(WorkbenchStore.Row::id).containsExactly(current.id());
        assertThat(com.ruanzhu.doorhandle.module.ai.testsupport.FixtureSourceSnapshot.capture(source,SOURCE_TABLES)).isEqualTo(snapshot);
    }
    @Test void rejectsUnregisteredPayloadFieldsBeforeTargetMutation(){
        seed();source.update("UPDATE agent_workbench_item SET payload=JSON_SET(payload,'$.arbitrary_unregistered_field','must not disappear')");
        assertThatThrownBy(()->migration.copy(admission)).isInstanceOf(IllegalArgumentException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance",Integer.class)).isZero();assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event",Integer.class)).isZero();
    }
    @Test void finalVerificationRollsBackEarlierItemCorruptionByALaterAuditTrigger(){
        seed();jdbc.execute("CREATE TRIGGER workbench_copy_corrupt AFTER INSERT ON audit_event FOR EACH ROW UPDATE workflow_instance SET payload_json=JSON_SET(payload_json,'$.legacy.payloadJson','tampered') WHERE kind='WORKBENCH_CHILD'");
        assertThatThrownBy(()->migration.copy(admission)).hasMessageContaining("Final complete target-column verification");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance",Integer.class)).isZero();assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event",Integer.class)).isZero();
        assertThat(source.queryForObject("SELECT payload FROM agent_workbench_item",String.class)).contains("保留原文");
    }
    @Test void targetCollisionIsNeverTreatedAsAnIdempotentRetry(){
        seed();migration.copy(admission);assertThatThrownBy(()->migration.copy(admission)).hasMessageContaining("not empty");
    }
    @Test void extraSourceColumnsAreNotSilentlyDropped(){
        seed();source.execute("ALTER TABLE agent_workbench_request ADD COLUMN unknown_business_evidence TEXT NULL");assertThatThrownBy(()->migration.copy(admission)).hasMessageContaining("complete original source column list");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance",Integer.class)).isZero();
    }
}
