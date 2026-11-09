package com.ruanzhu.doorhandle.module.detection.service.report;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.ruanzhu.doorhandle.contracts.detection.ReportLifecycleEvent;
import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowKind;
import com.ruanzhu.doorhandle.module.detection.dto.report.QualityReportDtos.View;
import com.ruanzhu.doorhandle.module.detection.repository.ReportEventRepository;
import com.ruanzhu.doorhandle.module.detection.repository.ReportWorkflowRepository;
import com.ruanzhu.doorhandle.module.detection.support.ReportMigrationFixture;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.Map;
import java.util.UUID;
import static org.assertj.core.api.Assertions.*;
import static com.ruanzhu.doorhandle.module.detection.EcsIsolatedMysql.assertCheckViolation;

/** Actual historical DDL, actual public baseline and unchanged copy script; ECS execution remains opt-in. */
@EnabledIfSystemProperty(named="report.copy.source-config",matches=".+")
class ReportWorkflowMigrationMySqlTest {
    ReportMigrationFixture fixture;JdbcTemplate jdbc,legacy;
    final ObjectMapper json=new ObjectMapper().findAndRegisterModules();
    final LocalDateTime beijing=LocalDateTime.of(2026,10,14,16,30),utc=beijing.minusHours(8);
    final String report="qr-"+UUID.randomUUID(),request="Legacy_Report_Create",token="b".repeat(64),hash="a".repeat(64);
    ReportLifecycleEvent event;String response,eventJson;

    @BeforeEach void setup() throws Exception {
        fixture=new ReportMigrationFixture();jdbc=fixture.target();legacy=fixture.source();
        legacy.update("""
                INSERT INTO detection_quality_report(report_id,owner_user_id,owner_username,task_id,title,narrative,status,version,
                  source_json,source_sha256,snapshot_sha256,submitted_at,decided_at,decider_user_id,decider_username,decision_reason,created_at,updated_at)
                VALUES(?,1,'alice','task-1','原始标题','原始意见','APPROVED',3,'{}',?,?,?, ?,3,'boss','已核对',?,?)
                """,report,hash,hash,beijing,beijing.plusMinutes(1),beijing,beijing.plusMinutes(1));
        jdbc.update("""
                INSERT INTO quality_report(report_id,owner_user_id,owner_username,task_id,title,narrative,status,version,
                  source_json,source_sha256,snapshot_sha256,submitted_at,decided_at,decider_user_id,decider_username,decision_reason,created_at,updated_at)
                SELECT report_id,owner_user_id,owner_username,task_id,title,narrative,status,version,
                  source_json,source_sha256,snapshot_sha256,submitted_at,decided_at,decider_user_id,decider_username,decision_reason,created_at,updated_at
                FROM `__SOURCE_SCHEMA__`.detection_quality_report
                """.replace("__SOURCE_SCHEMA__",fixture.sourceName()));
        var view=new View(report,null,1,"alice","task-1","原始标题","原始意见","DRAFT",1,Map.of(),hash,null,null,null,null,null,beijing,beijing);
        response=json.writerWithDefaultPrettyPrinter().writeValueAsString(view);
        legacy.update("INSERT INTO detection_report_command(actor_user_id,request_id,command_sha256,report_id,response_json,created_at) VALUES(1,?,?,?,?,?)",request,hash,report,response,beijing);
        legacy.update("INSERT INTO detection_report_confirmation(token,report_id,actor_user_id,report_version,snapshot_sha256,decision_sha256,expires_at,used_at) VALUES(?,?,3,2,?,?,?,?)",token,report,hash,hash,beijing.plusMinutes(10),beijing.plusMinutes(1));
        legacy.update("INSERT INTO detection_report_agent_origin(actor_user_id,request_id,report_id,report_version,run_id,call_id,tool_name,created_at) VALUES(1,?,?,1,'run-1','call-1','create_report_draft',?)",request,report,beijing);
        event=new ReportLifecycleEvent(UUID.randomUUID().toString(),report,1,"SUBMITTED",2,1);
        eventJson=json.writerWithDefaultPrettyPrinter().writeValueAsString(event);
        legacy.update("INSERT INTO detection_report_outbox(event_id,report_id,event_type,payload_json,delivery_status,created_at,attempts,next_attempt_at,delivered_at) VALUES(?,?,?,?,'DELIVERED',?,2,?,?)",event.eventId(),report,event.eventType(),eventJson,beijing,beijing,beijing.plusSeconds(5));
        legacy.update("INSERT INTO detection_report_event_receipt(event_id,report_id,event_type,report_version,payload_sha256,consumed_at) VALUES(?,?,?,2,?,?)",event.eventId(),report,event.eventType(),new ReportEventCodec(json).digest(event),beijing.plusSeconds(4));
        legacy.update("INSERT INTO detection_report_event_state(report_id,last_version,status,last_event_id,updated_at) VALUES(?,2,'SUBMITTED',?,?)",report,event.eventId(),beijing.plusSeconds(4));
        legacy.update("INSERT INTO detection_report_audit(report_id,actor_user_id,actor_username,action,before_status,after_status,report_version,reason,snapshot_sha256,created_at) VALUES(?,1,'alice','CREATE',NULL,'DRAFT',1,NULL,NULL,?)",report,beijing);
    }
    @AfterEach void close() throws Exception {if(fixture!=null)fixture.close();}

    void migrate() throws Exception {
        fixture.copy("+08:00");
    }
    void assertEmptyTargetOperations(){
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance",Long.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event",Long.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM runtime_state",Long.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM quality_report",Long.class)).isEqualTo(1);
    }
    @Test void validCopyPreservesImmutableResponsesReceiptReplayAndBeijingPresentation() throws Exception {
        migrate();
        assertThat(fixture.sourceName()).isNotEqualTo(fixture.targetName());
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE'",Long.class)).isEqualTo(29);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name LIKE 'detection_report_%'",Long.class)).isZero();
        var reports=new ReportWorkflowRepository(jdbc,json);
        var command=reports.command(1,request.toLowerCase(java.util.Locale.ROOT)).orElseThrow();
        assertThat(reports.commandPayload(command).responseJson()).isEqualTo(response);
        assertThat(command.createdAt()).isEqualTo(utc);
        assertThat(json.readValue(reports.commandPayload(command).responseJson(),View.class).createdAt()).isEqualTo(beijing);
        var confirmation=reports.workflows().findByRequest(WorkflowKind.REPORT_CONFIRMATION,"REPORT_CONFIRMATION",token).orElseThrow();
        assertThat(confirmation.status()).isEqualTo("USED");assertThat(confirmation.expiresAt()).isEqualTo(utc.plusMinutes(10));
        assertThat(confirmation.finishedAt()).isEqualTo(utc.plusMinutes(1));assertThat(confirmation.createdAt()).isNull();
        assertThat(confirmation.updatedAt()).isEqualTo(utc.plusMinutes(1));
        var delivery=new ReportEventRepository(jdbc);assertThat(delivery.get(event.eventId()).payload()).isEqualTo(eventJson);
        assertThat(delivery.get(event.eventId()).attempts()).isEqualTo(2);
        var inbox=new ReportEventInbox(jdbc,delivery,new ReportEventCodec(json),new DataSourceTransactionManager(fixture.targetDataSource()));
        assertThat(inbox.receive(report,json.writeValueAsString(event))).isFalse();
        assertThat(reports.events(report).get(0).deliveredAt()).isEqualTo(beijing.plusSeconds(5));
        assertThat(reports.events(report).get(0).consumedAt()).isEqualTo(beijing.plusSeconds(4));
        assertThat(reports.audit(report).get(0).createdAt()).isEqualTo(beijing);
        assertThat(reports.audit(report).get(0).callId()).isEqualTo("call-1");
        assertThat(jdbc.queryForObject("SELECT created_at FROM quality_report WHERE report_id=?",LocalDateTime.class,report)).isEqualTo(beijing);
    }
    @Test void unusedHistoricalConfirmationDoesNotInventCreationUpdateOrCompletion() throws Exception {
        legacy.update("UPDATE detection_report_confirmation SET used_at=NULL,expires_at=?",beijing.plusHours(2));
        migrate();
        var confirmation=new ReportWorkflowRepository(jdbc,json).workflows()
                .findByRequest(WorkflowKind.REPORT_CONFIRMATION,"REPORT_CONFIRMATION",token).orElseThrow();
        assertThat(confirmation.createdAt()).isNull();assertThat(confirmation.updatedAt()).isNull();
        assertThat(confirmation.finishedAt()).isNull();assertThat(confirmation.status()).isEqualTo("PENDING");
        assertThat(confirmation.expiresAt()).isEqualTo(utc.plusHours(2));
        assertCheckViolation(()->jdbc.update("UPDATE workflow_instance SET legacy_source=NULL WHERE kind='REPORT_CONFIRMATION'"),
                "ck_workflow_legacy", "ck_legacy_clock_binding_workflow_instance");
        assertThat(legacy.queryForObject("SELECT used_at FROM detection_report_confirmation",LocalDateTime.class)).isNull();
    }
    @ParameterizedTest
    @CsvSource({"detection_report_command,created_at", "detection_report_confirmation,expires_at",
            "detection_report_confirmation,used_at", "detection_report_outbox,created_at",
            "detection_report_outbox,next_attempt_at", "detection_report_outbox,lease_expires_at",
            "detection_report_outbox,delivered_at", "detection_report_event_state,updated_at",
            "detection_report_event_receipt,consumed_at", "detection_report_audit,created_at",
            "detection_report_agent_origin,created_at"})
    void everyHistoricalTimeMustReallyConvertBeforeAnyCopy(String table,String column) {
        for(var value:java.util.List.of(LocalDateTime.of(1960,1,2,3,4,5),LocalDateTime.of(9999,1,2,3,4,5))) {
            legacy.update("UPDATE "+table+" SET "+column+"=?",value);
            assertThatThrownBy(this::migrate).isInstanceOf(org.springframework.jdbc.datasource.init.ScriptStatementFailedException.class)
                    .hasMessageContaining("TIMESTAMPDIFF(MICROSECOND");
            assertEmptyTargetOperations();
            assertThat(legacy.queryForList("SELECT "+column+" FROM "+table,LocalDateTime.class)).containsOnly(value);
        }
    }
    @ParameterizedTest @ValueSource(strings={"+00:00","-05:30"})
    void declaredOffsetPreservesEveryKnownHistoricalTime(String offset) throws Exception {
        // The actual V21/V30 source records seconds, with no fractional component.
        var next=beijing.plusSeconds(2);
        legacy.update("UPDATE detection_report_outbox SET next_attempt_at=?",next);
        fixture.copy(offset);
        int seconds=ZoneOffset.of(offset).getTotalSeconds();
        assertThat(jdbc.queryForObject("SELECT expires_at FROM workflow_instance WHERE kind='REPORT_CONFIRMATION'",LocalDateTime.class))
                .isEqualTo(beijing.plusMinutes(10).minusSeconds(seconds));
        assertThat(jdbc.queryForObject("SELECT created_at FROM workflow_instance WHERE kind='REPORT_CONFIRMATION'",LocalDateTime.class)).isNull();
        assertThat(jdbc.queryForObject("SELECT finished_at FROM workflow_instance WHERE kind='REPORT_CONFIRMATION'",LocalDateTime.class))
                .isEqualTo(beijing.plusMinutes(1).minusSeconds(seconds));
        assertThat(jdbc.queryForObject("SELECT next_attempt_at FROM workflow_instance WHERE kind='REPORT_DELIVERY'",LocalDateTime.class)).isEqualTo(next.minusSeconds(seconds));
        assertThat(jdbc.queryForObject("SELECT occurred_at FROM audit_event WHERE kind='QUALITY_REPORT'",LocalDateTime.class)).isEqualTo(beijing.minusSeconds(seconds));
        assertThat(jdbc.queryForObject("SELECT updated_at FROM runtime_state WHERE namespace='REPORT_EVENT_STATE'",LocalDateTime.class))
                .isEqualTo(beijing.plusSeconds(4).minusSeconds(seconds));
    }
    @ParameterizedTest @ValueSource(strings={"extra-column","timestamp-precision","missing-index","source-trigger","source-collation"})
    void unreviewedSourceStructureCannotBePartiallyCopied(String drift) {
        switch(drift) {
            case "extra-column"->legacy.execute("ALTER TABLE detection_report_audit ADD COLUMN unreviewed_value VARCHAR(30) NULL");
            case "timestamp-precision"->legacy.execute("ALTER TABLE detection_report_confirmation MODIFY expires_at DATETIME(6) NOT NULL");
            case "missing-index"->legacy.execute("DROP INDEX idx_report_confirmation_expiry ON detection_report_confirmation");
            case "source-trigger"->legacy.execute("CREATE TRIGGER unreviewed_confirmation BEFORE UPDATE ON detection_report_confirmation FOR EACH ROW SET NEW.actor_user_id=NEW.actor_user_id");
            case "source-collation"->legacy.execute("ALTER TABLE detection_report_command MODIFY request_id VARCHAR(64) COLLATE utf8mb4_bin NOT NULL");
            default->throw new IllegalArgumentException(drift);
        }
        assertThatThrownBy(this::migrate).isInstanceOf(org.springframework.jdbc.datasource.init.ScriptStatementFailedException.class);
        assertEmptyTargetOperations();
        assertThat(legacy.queryForObject("SELECT COUNT(*) FROM detection_report_confirmation",Long.class)).isEqualTo(1);
    }
    @ParameterizedTest @ValueSource(strings={"REPORT_COMMAND","REPORT_CONFIRMATION","REPORT_AGENT_ORIGIN","REPORT_DELIVERY","REPORT_CONSUMPTION","QUALITY_REPORT","REPORT_EVENT_STATE","confirmation-time","confirmation-owner"})
    void fullReconciliationRejectsAdditionalOrRewrittenState(String corruption) {
        if(corruption.equals("QUALITY_REPORT"))
            jdbc.execute("CREATE TRIGGER corrupt_report_field BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.quantity=17,NEW.unit='BYTES'");
        else if(corruption.equals("REPORT_EVENT_STATE"))
            jdbc.execute("CREATE TRIGGER corrupt_report_field BEFORE INSERT ON runtime_state FOR EACH ROW SET NEW.payload_version=2");
        else if(corruption.equals("confirmation-time"))
            jdbc.execute("CREATE TRIGGER corrupt_report_field BEFORE INSERT ON workflow_instance FOR EACH ROW SET NEW.created_at=IF(NEW.kind='REPORT_CONFIRMATION','2026-10-14 08:00:00',NEW.created_at)");
        else if(corruption.equals("confirmation-owner"))
            jdbc.execute("CREATE TRIGGER corrupt_report_field BEFORE INSERT ON workflow_instance FOR EACH ROW SET NEW.owner_user_id=IF(NEW.kind='REPORT_CONFIRMATION',99,NEW.owner_user_id)");
        else jdbc.execute("CREATE TRIGGER corrupt_report_field BEFORE INSERT ON workflow_instance FOR EACH ROW SET NEW.error_code=IF(NEW.kind='"+corruption+"','INJECTED',NEW.error_code)");
        assertThatThrownBy(this::migrate).isInstanceOf(org.springframework.jdbc.datasource.init.ScriptStatementFailedException.class);
        assertEmptyTargetOperations();
        assertThat(legacy.queryForObject("SELECT actor_user_id FROM detection_report_confirmation",Long.class)).isEqualTo(3);
    }
    @ParameterizedTest @ValueSource(strings={"missing-command-version","null-command-version","string-command-version","huge-command-version","null-command-owner","null-command-source","missing-command-status","null-command-created","missing-schema","null-schema","string-schema","missing-status","null-status","lowercase-status","null-actor","huge-actor","huge-event-version"})
    void invalidRequiredJsonFieldsAbortBeforeAnyTargetWrite(String corruption) throws Exception {
        boolean command=corruption.contains("command");var body=(ObjectNode)json.readTree(command?response:eventJson);
        switch(corruption){
            case "missing-command-version"->body.remove("version");case "null-command-version"->body.putNull("version");
            case "string-command-version"->body.put("version","1");case "huge-command-version"->body.put("version",2147483648L);
            case "null-command-owner"->body.putNull("ownerUserId");case "null-command-source"->body.putNull("source");
            case "missing-command-status"->body.remove("status");case "null-command-created"->body.putNull("createdAt");
            case "missing-schema"->{body.remove("schemaVersion");body.put("unexpected",1);}case "null-schema"->body.putNull("schemaVersion");
            case "string-schema"->body.put("schemaVersion","1");case "missing-status"->{body.remove("status");body.put("unexpected","SUBMITTED");}
            case "null-status"->body.putNull("status");case "lowercase-status"->body.put("status","submitted");
            case "null-actor"->body.putNull("actorUserId");case "huge-actor"->body.put("actorUserId",new java.math.BigInteger("9223372036854775808"));
            case "huge-event-version"->body.put("version",2147483648L);default->throw new IllegalArgumentException(corruption);
        }
        if(command)legacy.update("UPDATE detection_report_command SET response_json=?",json.writeValueAsString(body));
        else legacy.update("UPDATE detection_report_outbox SET payload_json=?",json.writeValueAsString(body));
        assertThatThrownBy(this::migrate).isInstanceOf(org.springframework.jdbc.datasource.init.ScriptStatementFailedException.class);
        assertEmptyTargetOperations();
    }
    @ParameterizedTest @ValueSource(strings={"receipt-hash","state-status","missing-state","delivery-finish","confirmation-expiry"})
    void inconsistentSourceRelationshipsFailClosed(String corruption){
        switch(corruption){
            case "receipt-hash"->legacy.update("UPDATE detection_report_event_receipt SET payload_sha256=?","0".repeat(64));
            case "state-status"->legacy.update("UPDATE detection_report_event_state SET status='APPROVED'");
            case "missing-state"->legacy.update("DELETE FROM detection_report_event_state");
            case "delivery-finish"->legacy.update("UPDATE detection_report_outbox SET delivery_status='PENDING'");
            case "confirmation-expiry"->legacy.update("UPDATE detection_report_confirmation SET used_at=expires_at");
            default->throw new IllegalArgumentException(corruption);
        }
        assertThatThrownBy(this::migrate).isInstanceOf(org.springframework.jdbc.datasource.init.ScriptStatementFailedException.class);
        assertEmptyTargetOperations();
    }
    @Test void sourceExpiredDeliveryLeaseRetainsAttemptsAndRejectsOldWorkerAfterRecovery() throws Exception {
        legacy.update("UPDATE detection_report_outbox SET delivery_status='PROCESSING',delivered_at=NULL,lease_token='old-worker',lease_expires_at=?",beijing.plusMinutes(1));
        migrate();var repository=new ReportEventRepository(jdbc);var old=repository.get(event.eventId());
        assertThat(old.attempts()).isEqualTo(2);assertThat(old.leaseToken()).isEqualTo("old-worker");
        var now=LocalDateTime.now(ZoneOffset.UTC);var reclaimed=repository.claim(old,now,now.plusMinutes(1));
        assertThat(reclaimed).isNotNull();assertThat(reclaimed.attempts()).isEqualTo(3);
        assertThat(repository.delivered(event.eventId(),"old-worker",now)).isFalse();
        assertThat(repository.delivered(event.eventId(),reclaimed.leaseToken(),now)).isTrue();
    }
    @Test void targetConstraintFailureRollsBackRowsAlreadyCopied(){
        jdbc.execute("ALTER TABLE audit_event ADD CONSTRAINT fail_copied_report_audit CHECK(kind<>'QUALITY_REPORT')");
        assertThatThrownBy(this::migrate).isInstanceOf(org.springframework.jdbc.datasource.init.ScriptStatementFailedException.class);
        assertEmptyTargetOperations();
    }
    @ParameterizedTest @ValueSource(strings={"missing-response","wrong-identity"})
    void finalCopyChecksRejectMissingPayloadAndMismatchedRowsDespiteEqualCounts(String corruption){
        if("missing-response".equals(corruption))
            jdbc.execute("CREATE TRIGGER corrupt_report_copy BEFORE INSERT ON workflow_instance FOR EACH ROW SET NEW.payload_json=IF(NEW.kind='REPORT_COMMAND',JSON_OBJECT(),NEW.payload_json)");
        else jdbc.execute("CREATE TRIGGER corrupt_report_copy BEFORE INSERT ON workflow_instance FOR EACH ROW SET NEW.request_id=IF(NEW.kind='REPORT_COMMAND','Wrong_Request_Key',NEW.request_id)");
        assertThatThrownBy(this::migrate).isInstanceOf(org.springframework.jdbc.datasource.init.ScriptStatementFailedException.class);
        assertEmptyTargetOperations();
    }
    @ParameterizedTest @ValueSource(strings={"PENDING","RETRY","PROCESSING","FAILED"})
    void unresolvedSourceCannotBeClaimedRetriedDeferredAcknowledgedOrConsumed(String originalStatus)throws Exception{
        legacy.update("UPDATE detection_report_outbox SET delivery_status=?,delivered_at=NULL,lease_token=?,lease_expires_at=?",originalStatus,
                "PROCESSING".equals(originalStatus)?"old-worker":null,"PROCESSING".equals(originalStatus)?beijing.plusMinutes(1):null);
        String sourceHash=fixture.sourceSnapshotSha256();fixture.copyUnresolved();
        var repository=new ReportEventRepository(jdbc);var reports=new ReportWorkflowRepository(jdbc,json);var entry=repository.get(event.eventId());
        assertThat(entry.status()).isEqualTo(originalStatus);assertThat(entry.clockStatus()).isEqualTo("UNRESOLVED");assertThat(entry.payload()).isEqualTo(eventJson);
        var retained=jdbc.queryForList("SELECT * FROM workflow_instance ORDER BY id");var retainedState=jdbc.queryForList("SELECT * FROM runtime_state ORDER BY namespace,owner_id,scope_key");
        var future=LocalDateTime.of(2030,1,1,0,0);assertThat(repository.due(future,100)).isEmpty();assertThat(repository.claim(entry,future,future.plusMinutes(1))).isNull();
        var stale=new ReportEventRepository.Entry(entry.eventId(),entry.reportId(),entry.eventType(),entry.payload(),entry.status(),entry.attempts(),entry.leaseToken());
        assertThat(repository.claim(stale,future,future.plusMinutes(1))).isNull();repository.defer(stale,future);
        assertThat(repository.delivered(event.eventId(),"old-worker",future)).isFalse();assertThat(repository.failed(event.eventId(),"old-worker","RETRY",false,future)).isFalse();
        var transaction=new org.springframework.transaction.support.TransactionTemplate(new DataSourceTransactionManager(fixture.targetDataSource()));
        transaction.executeWithoutResult(status->assertThat(reports.retry(report,event.eventId(),entry.attempts())).isFalse());
        var inbox=new ReportEventInbox(jdbc,repository,new ReportEventCodec(json),new DataSourceTransactionManager(fixture.targetDataSource()));
        assertThatThrownBy(()->inbox.receive(report,json.writeValueAsString(event))).isInstanceOf(IllegalStateException.class).hasMessageContaining("历史报告");
        var confirmation=reports.workflows().findByRequest(WorkflowKind.REPORT_CONFIRMATION,"REPORT_CONFIRMATION",token).orElseThrow();
        assertThatThrownBy(()->transaction.executeWithoutResult(status->reports.consumeConfirmation(confirmation))).hasMessageContaining("历史确认时间需核对");
        assertThatThrownBy(()->reports.command(1,request)).hasMessageContaining("历史报告操作时间需核对");
        assertThat(jdbc.queryForList("SELECT * FROM workflow_instance ORDER BY id")).isEqualTo(retained);
        assertThat(jdbc.queryForList("SELECT * FROM runtime_state ORDER BY namespace,owner_id,scope_key")).isEqualTo(retainedState);
        String sidecar=jdbc.queryForObject("SELECT legacy_clock_json FROM workflow_instance WHERE kind='REPORT_DELIVERY'",String.class);
        assertThat(json.readTree(sidecar).path("sourceSnapshotSha256").asText()).isEqualTo(sourceHash);assertThat(fixture.sourceSnapshotSha256()).isEqualTo(sourceHash);
    }
    @Test void unknownHistoryIsReadableWithoutManufacturedTimesAndNewDeliveryStillWorks()throws Exception{
        fixture.copyUnresolved();var reports=new ReportWorkflowRepository(jdbc,json);var repository=new ReportEventRepository(jdbc);
        assertThat(reports.events(report)).singleElement().satisfies(view->{assertThat(view.deliveryStatus()).isEqualTo("DELIVERED");assertThat(view.clockStatus()).isEqualTo("UNRESOLVED");assertThat(view.nextAttemptAt()).isNull();assertThat(view.deliveredAt()).isNull();assertThat(view.consumedAt()).isNull();assertThat(view.sourceWallTimes()).containsEntry("created_at","2026-10-14 16:30:00");});
        assertThat(reports.audit(report)).singleElement().satisfies(view->{assertThat(view.createdAt()).isNull();assertThat(view.clockStatus()).isEqualTo("UNRESOLVED");assertThat(view.sourceWallTimes()).containsEntry("created_at","2026-10-14 16:30:00");});
        var next=new ReportLifecycleEvent(UUID.randomUUID().toString(),report,1,"APPROVED",3,1);String body=json.writeValueAsString(next);
        var current=new com.ruanzhu.doorhandle.module.detection.repository.QualityReportRepository(jdbc).get(report,false);
        var transaction=new org.springframework.transaction.support.TransactionTemplate(new DataSourceTransactionManager(fixture.targetDataSource()));
        transaction.executeWithoutResult(status->reports.enqueue(current,1,next.eventId(),next.eventType(),body));
        var candidate=repository.get(next.eventId());assertThat(candidate.legacyClockUnresolved()).isFalse();
        var now=LocalDateTime.now(ZoneOffset.UTC);var claimed=repository.claim(candidate,now,now.plusMinutes(1));assertThat(claimed).isNotNull();
        var inbox=new ReportEventInbox(jdbc,repository,new ReportEventCodec(json),new DataSourceTransactionManager(fixture.targetDataSource()));
        assertThat(inbox.receive(report,body)).isTrue();assertThat(repository.delivered(next.eventId(),claimed.leaseToken(),now)).isTrue();
        assertThat(repository.get(event.eventId()).clockStatus()).isEqualTo("UNRESOLVED");assertThat(repository.get(event.eventId()).status()).isEqualTo("DELIVERED");
    }
    @Test void fixtureSourceSnapshotIncludesOriginalNullableValuesAndCompleteRawPayload()throws Exception{
        String original=fixture.sourceSnapshotSha256();legacy.update("UPDATE detection_report_audit SET reason='原始备注 ' WHERE report_id=?",report);
        assertThat(fixture.sourceSnapshotSha256()).isNotEqualTo(original);
        legacy.update("UPDATE detection_report_audit SET reason=NULL WHERE report_id=?",report);assertThat(fixture.sourceSnapshotSha256()).isEqualTo(original);
        legacy.update("UPDATE detection_report_command SET response_json=CONCAT(response_json,' ') WHERE report_id=?",report);
        assertThat(fixture.sourceSnapshotSha256()).isNotEqualTo(original);
    }
}
