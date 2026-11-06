package com.ruanzhu.doorhandle.module.detection.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.agent.OperationsAuditApi;
import com.ruanzhu.doorhandle.contracts.security.BusinessAccountLookupApi;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.detection.support.CompactDetectionMySqlFixture;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.support.TransactionTemplate;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Business authorization and immutable evidence on the complete compact ECS schema. */
@EnabledIfSystemProperty(named="detection.identity.mysql.config",matches=".+")
class IdentityEvidenceMySqlTest {
    private static final String REVISION="a".repeat(64);
    private final AgentActor boss=new AgentActor(1,"boss",AgentActor.Role.SUPERVISOR);
    private final AgentActor alice=new AgentActor(2,"alice",AgentActor.Role.INSPECTOR);
    CompactDetectionMySqlFixture fixture;
    JdbcTemplate jdbc;
    TransactionTemplate tx;
    DetectionIdentityService identity;
    DetectionIdentityReviewService review;
    DetectionIdentityEvidenceService evidence;
    DetectionIdentityReconciliationService reconciliation;

    @BeforeEach void setup() throws Exception {
        fixture=new CompactDetectionMySqlFixture("detection.identity.mysql.config");
        jdbc=new JdbcTemplate(fixture.source());
        tx=new TransactionTemplate(new DataSourceTransactionManager(fixture.source()));
        for(String[] control:List.of(new String[]{"DETECTION_IDENTITY_CONTROL","PREVIEW"},
                new String[]{"DETECTION_IDENTITY_SOURCE_CONTROL","COLLECTING"}))
            jdbc.update("INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,state_code,payload_version,payload_json,created_at,updated_at) VALUES(?,0,'1',0,?,1,JSON_OBJECT('controlId',1,'activationRevision',NULL,'legacySource',NULL),UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",control[0],control[1]);
        var accounts=mock(BusinessAccountLookupApi.class);
        var users=mock(BusinessUserDirectory.class);
        var audit=mock(OperationsAuditApi.class);
        for(AgentActor actor:List.of(boss,alice)) {
            var current=new BusinessUserDirectory.Identity(actor.userId(),actor.username(),actor.userId()==1);
            when(users.current(actor.userId(),actor.username())).thenReturn(current);
            when(users.lockCurrent(actor.userId(),actor.username())).thenReturn(current);
        }
        when(accounts.findExactUserId("alice")).thenReturn(2L);
        when(accounts.describe(2L)).thenReturn(new BusinessAccountLookupApi.Account(2,"alice","INSPECTOR",REVISION));
        when(accounts.lock(any())).thenAnswer(call->call.getArgument(0));
        var json=new ObjectMapper();
        evidence=new DetectionIdentityEvidenceService(jdbc,accounts,users,audit,json);
        ReflectionTestUtils.setField(evidence,"identityEnabled",true);
        ReflectionTestUtils.setField(evidence,"reviewEnabled",true);
        ReflectionTestUtils.setField(evidence,"missingNameReview",true);
        review=new DetectionIdentityReviewService(jdbc,accounts,users,audit,json);
        ReflectionTestUtils.setField(review,"enabled",true);
        ReflectionTestUtils.setField(review,"missingNameReview",true);
        review.evidenceService(evidence);
        identity=new DetectionIdentityService(jdbc,accounts,users,audit,json);
        identity.reviewService(review);identity.evidenceService(evidence);
        reconciliation=new DetectionIdentityReconciliationService(jdbc,users,accounts,evidence,audit,json);
        ReflectionTestUtils.setField(reconciliation,"maxTasks",20000);
        ReflectionTestUtils.setField(reconciliation,"maxReports",20);
        evidence.schema();review.schema();reconciliation.schema();
    }
    @AfterEach void close(){if(fixture!=null)fixture.close();}

    @Test void creationReplayIsIdempotentAndAChangedRequestCannotOverwriteItsEvidence() {
        newTask("t-created");
        tx.executeWithoutResult(s->evidence.record("t-created","created",alice,"NEW_CREATION","create-1",null));
        tx.executeWithoutResult(s->evidence.record("t-created","created",alice,"NEW_CREATION","create-1",null));
        assertThat(count("audit_event","kind='DETECTION_IDENTITY_BINDING_EVENT'")).isEqualTo(1);
        assertThat(evidence.matches("t-created","created")).isTrue();
        assertThat(evidence.sources(List.of("t-created")).get("t-created").get("created"))
                .containsEntry("state","SOURCE_RECORDED").containsEntry("bound_identity_name","alice");
        assertThatThrownBy(()->tx.executeWithoutResult(s->evidence.record("t-created","created",alice,"SUPERVISOR_MAPPING","create-1",null)))
                .hasMessageContaining("主管回填依据");
        assertThatThrownBy(()->jdbc.update("UPDATE audit_event SET action='changed' WHERE kind='DETECTION_IDENTITY_BINDING_EVENT'"))
                .isInstanceOf(DataAccessException.class);
        assertThatThrownBy(()->jdbc.update("DELETE FROM audit_event WHERE kind='DETECTION_IDENTITY_BINDING_EVENT'"))
                .isInstanceOf(DataAccessException.class);
        assertThat(count("audit_event","kind='DETECTION_IDENTITY_BINDING_EVENT'")).isEqualTo(1);
    }

    @Test void vacantRoleAppendsAnUnattributedClearAndKeepsItsPreviousSourceFact() {
        newTask("t-clear");
        jdbc.update("UPDATE detection_task SET reviewer='alice',reviewer_user_id=2,reviewer_identity_name='alice' WHERE task_id='t-clear'");
        tx.executeWithoutResult(s->evidence.record("t-clear","reviewer",alice,"PERFORMED_OPERATION","review-1",null));
        jdbc.update("UPDATE detection_task SET reviewer=NULL,reviewer_user_id=NULL,reviewer_identity_name=NULL WHERE task_id='t-clear'");
        tx.executeWithoutResult(s->evidence.invalidateVacant("t-clear"));
        tx.executeWithoutResult(s->evidence.invalidateVacant("t-clear"));
        var events=jdbc.queryForList("SELECT * FROM ("+DetectionIdentityPersistence.EVENTS+") e ORDER BY revision");
        assertThat(events).hasSize(2);
        assertThat(events.get(0)).containsEntry("source_kind","PERFORMED_OPERATION").containsEntry("actor_name","alice");
        assertThat(events.get(1)).containsEntry("source_kind","OBSERVED_CLEAR").containsEntry("actor_user_id",null)
                .containsEntry("bound_user_id",null).containsEntry("previous_sha256",events.get(0).get("event_sha256"));
        assertThat(evidence.matches("t-clear","reviewer")).isFalse();
        assertThat(evidence.sources(List.of("t-clear")).get("t-clear").get("reviewer"))
                .containsEntry("source_kind","OBSERVED_CLEAR").containsEntry("state","SOURCE_INVALID");
    }

    @SuppressWarnings("unchecked")
    @Test void missingNameNeedsItsExactCertificateAndCannotBeReboundByAnUnrelatedProof() {
        jdbc.update("INSERT INTO detection_task(task_id,created_by,status) VALUES('t-missing',NULL,'PENDING')");
        var rows=(List<Map<String,Object>>)review.preview(boss,"",10,false).get("records");
        var row=rows.get(0);
        assertThat(row).containsEntry("missingName",true).containsEntry("suggestedUserId",null);
        var mapping=new DetectionIdentityService.Mapping("t-missing","created","",row.get("snapshot").toString(),2L,
                "alice","INSPECTOR",REVISION,"SOURCE_RECORD_CHECKED");
        var wrongProof=new DetectionIdentityService.MissingNameConfirmation("other-task","created","archive:42",true);
        assertThatThrownBy(()->tx.executeWithoutResult(s->review.apply(boss,new DetectionIdentityService.Apply("map-bad",List.of(mapping),0L,true,List.of(wrongProof)))))
                .hasMessageContaining("逐条对应");
        assertThat(count("workflow_instance","kind='DETECTION_IDENTITY_MAP_BATCH'")).isZero();
        var proof=new DetectionIdentityService.MissingNameConfirmation("t-missing","created","archive:42",true);
        var command=new DetectionIdentityService.Apply("map-missing",List.of(mapping),0L,true,List.of(proof));
        Map<String,Object> applied=tx.execute(s->review.apply(boss,command));
        assertThat(applied).containsEntry("protocol","identity-map-v3").containsEntry("missingNameCount",1);
        Map<String,Object> replayed=tx.execute(s->review.apply(boss,command));
        assertThat(replayed).containsEntry("replayed",true);
        assertThat(evidence.confirmedMissingName("t-missing","created")).isTrue();
        tx.executeWithoutResult(s->identity.activate(boss,1,"activate-missing",true));
        assertThat(identity.active()).isTrue();assertThat(evidence.active()).isTrue();
        assertThat(identity.canAccess("t-missing",2)).isTrue();
        var saved=review.status(boss,"map-missing");
        var mappings=(List<Map<String,Object>>)saved.get("mappings");
        assertThat((Map<String,Object>)mappings.get(0).get("missingNameConfirmation"))
                .containsEntry("original_name",null).containsEntry("evidence_reference","archive:42");
        assertThatThrownBy(()->jdbc.update("UPDATE workflow_instance SET status='FAILED' WHERE kind='DETECTION_IDENTITY_MAP_BATCH'"))
                .isInstanceOf(DataAccessException.class);
        assertThatThrownBy(()->jdbc.update("DELETE FROM audit_event WHERE kind='DETECTION_IDENTITY_MISSING_NAME'"))
                .isInstanceOf(DataAccessException.class);
        jdbc.update("UPDATE detection_task SET created_by='alice' WHERE task_id='t-missing'");
        assertThat(evidence.confirmedMissingName("t-missing","created")).isFalse();
        assertThat(identity.canAccess("t-missing",2)).isFalse();
    }

    @SuppressWarnings("unchecked")
    @Test void reconciliationPreservesAllIssueFieldsAndComparesCompletedSnapshotsWithoutRepairingTasks() {
        newTask("t-report");
        tx.executeWithoutResult(s->evidence.record("t-report","created",alice,"NEW_CREATION","report-create",null));
        var first=tx.execute(s->reconciliation.create(boss,new DetectionIdentityReconciliationService.Create("report-1",0L,true)));
        assertThat(first).containsEntry("taskCount",1L).containsEntry("roleCount",5L).containsEntry("issueCount",0L);
        jdbc.update("UPDATE detection_task SET reviewer='legacy reviewer',reviewer_user_id=2,reviewer_identity_name='alice' WHERE task_id='t-report'");
        var second=tx.execute(s->reconciliation.create(boss,new DetectionIdentityReconciliationService.Create("report-2",0L,true)));
        assertThat(second).containsEntry("issueCount",1L);
        var summary=(Map<String,Object>)second.get("summary");
        assertThat(summary).containsEntry("datasetChanged","CHANGED");
        assertThat(((Map<String,Object>)summary.get("comparison")).get("newIssueRows")).isEqualTo(1);
        var issueRows=(List<Map<String,Object>>)reconciliation.items(boss,"report-2",0,10).get("records");
        assertThat(issueRows).hasSize(1);
        assertThat(issueRows.get(0)).containsEntry("task_id","t-report").containsEntry("identity_role","reviewer")
                .containsEntry("existing_name","legacy reviewer").containsEntry("identity_name","alice")
                .containsEntry("current_username","alice").containsEntry("current_role","INSPECTOR")
                .containsEntry("current_revision",REVISION).containsEntry("source_kind",null)
                .containsEntry("source_request_id",null).containsEntry("source_sha256",null);
        assertThat((List<String>)issueRows.get(0).get("reasons")).containsExactly("SNAPSHOT_MISMATCH","SOURCE_UNVERIFIED");
        var third=tx.execute(s->reconciliation.create(boss,new DetectionIdentityReconciliationService.Create("report-3",0L,true)));
        assertThat((Map<String,Object>)third.get("summary")).containsEntry("datasetChanged","UNCHANGED");
        Map<String,Object> replayed=tx.execute(s->reconciliation.create(boss,new DetectionIdentityReconciliationService.Create("report-3",0L,true)));
        assertThat(replayed).containsEntry("replayed",true).containsEntry("datasetDigest",third.get("datasetDigest"));
        assertThat(count("workflow_instance","kind='DETECTION_IDENTITY_REPORT'")).isEqualTo(3);
        assertThat(jdbc.queryForObject("SELECT reviewer FROM detection_task WHERE task_id='t-report'",String.class)).isEqualTo("legacy reviewer");
        assertThatThrownBy(()->jdbc.update("UPDATE workflow_instance SET payload_json=JSON_SET(payload_json,'$.issueCount',0) WHERE kind='DETECTION_IDENTITY_REPORT'"))
                .isInstanceOf(DataAccessException.class);
    }
    private void newTask(String task) {
        jdbc.update("INSERT INTO detection_task(task_id,created_by,created_user_id,created_identity_name,status) VALUES(?,'alice',2,'alice','PENDING')",task);
    }
    private int count(String table,String predicate){return jdbc.queryForObject("SELECT COUNT(*) FROM "+table+" WHERE "+predicate,Integer.class);}
}
