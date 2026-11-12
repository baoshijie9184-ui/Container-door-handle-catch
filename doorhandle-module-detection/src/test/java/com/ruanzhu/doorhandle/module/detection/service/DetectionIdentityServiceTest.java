package com.ruanzhu.doorhandle.module.detection.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.*;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.transaction.support.TransactionTemplate;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@org.junit.jupiter.api.condition.EnabledIfSystemProperty(named="detection.identity.mysql.config",matches=".+")
class DetectionIdentityServiceTest {
    com.ruanzhu.doorhandle.module.detection.support.CompactDetectionMySqlFixture fixture;
    @AfterEach void close(){if(fixture!=null)fixture.close();}
    JdbcTemplate jdbc;BusinessAccountLookupApi accounts;BusinessUserDirectory users;OperationsAuditApi audit;DetectionIdentityService service;TransactionTemplate tx;
    final ObjectMapper json=new ObjectMapper().findAndRegisterModules();
    AgentActor boss=new AgentActor(1,"boss",AgentActor.Role.SUPERVISOR),alice=new AgentActor(2,"alice",AgentActor.Role.INSPECTOR);
    @BeforeEach void setup() throws Exception {
        fixture=new com.ruanzhu.doorhandle.module.detection.support.CompactDetectionMySqlFixture("detection.identity.mysql.config");
        var source=fixture.source();jdbc=new JdbcTemplate(source);tx=new TransactionTemplate(new DataSourceTransactionManager(source));
        jdbc.update("INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,state_code,payload_version,payload_json,created_at,updated_at) VALUES('DETECTION_IDENTITY_CONTROL',0,'1',0,'PREVIEW',1,JSON_OBJECT('controlId',1,'activationRevision',NULL,'legacySource',NULL),UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))");
        accounts=mock(BusinessAccountLookupApi.class);users=mock(BusinessUserDirectory.class);audit=mock(OperationsAuditApi.class);when(accounts.findExactUserId("alice")).thenReturn(2L);when(accounts.findExactUserId("orphan")).thenReturn(null);when(accounts.username(2)).thenReturn("alice");when(users.current(1,"boss")).thenReturn(new BusinessUserDirectory.Identity(1,"boss",true));when(users.current(2,"alice")).thenReturn(new BusinessUserDirectory.Identity(2,"alice",false));service=new DetectionIdentityService(jdbc,accounts,users,audit,json);jdbc.update("INSERT INTO detection_task(task_id,created_by,assignee,status) VALUES('t1','alice','orphan','PENDING')");
        enableCurrentReviewProtocol();
    }
    void enableCurrentReviewProtocol() throws Exception {
        when(users.lockCurrent(1,"boss")).thenReturn(new BusinessUserDirectory.Identity(1,"boss",true));
        when(accounts.describe(2)).thenReturn(new BusinessAccountLookupApi.Account(2,"alice","INSPECTOR","a".repeat(64)));
        when(accounts.lock(any())).thenAnswer(call->call.getArgument(0));
        var review=new DetectionIdentityReviewService(jdbc,accounts,users,audit,json);
        org.springframework.test.util.ReflectionTestUtils.setField(review,"enabled",true);
        review.schema();service.reviewService(review);
    }
    @SuppressWarnings("unchecked") List<Map<String,Object>> preview(){return (List<Map<String,Object>>)service.preview(boss,"",100,false).get("records");}
    DetectionIdentityService.Apply mappings(String request){return new DetectionIdentityService.Apply(request,preview().stream().map(row->new DetectionIdentityService.Mapping((String)row.get("taskId"),(String)row.get("role"),(String)row.get("expectedName"),(String)row.get("snapshot"),2L,"alice","INSPECTOR","a".repeat(64),"MANUAL_RECONCILIATION")).toList(),jdbc.queryForObject("SELECT revision FROM runtime_state WHERE namespace='DETECTION_IDENTITY_CONTROL' AND owner_id=0 AND scope_key='1'",Long.class),true);}
    @Test void unmappedTasksCannotActivateAndPreviewDoesNotGuessUnknownAccounts(){assertThat(service.active()).isFalse();assertThat(preview()).anyMatch(row->row.get("expectedName").equals("orphan")&&row.get("suggestedUserId")==null);assertThatThrownBy(()->service.activate(boss,0,"activate")).hasMessageContaining("未完成映射");assertThatThrownBy(()->service.preview(alice,"",10)).isInstanceOf(SecurityException.class);}
    @Test void confirmedStableIdsKeepOwnershipWhenAnAccountNameIsReusedAndLegacyAssignmentChangesAreDenied(){var request=mappings("map-1");tx.executeWithoutResult(s->service.apply(boss,request));tx.executeWithoutResult(s->service.activate(boss,1,"activate"));assertThat(service.active()).isTrue();assertThat(service.canAccess("t1",2)).isTrue();when(accounts.findExactUserId("alice")).thenReturn(99L);assertThat(service.canAccess("t1",99)).isFalse();jdbc.update("UPDATE detection_task SET created_user_id=77,assignee='legacy-other' WHERE task_id='t1'");assertThat(service.canAccess("t1",2)).isFalse();assertThat(service.apply(boss,request)).containsEntry("replayed",true);}
    @Test void stalePreviewAndAuditFailureCannotPartiallyChangeOwnership(){var stale=mappings("map-stale");jdbc.update("UPDATE detection_task SET created_by='changed' WHERE task_id='t1'");assertThatThrownBy(()->tx.executeWithoutResult(s->service.apply(boss,stale))).hasMessageContaining("已变化");jdbc.update("UPDATE detection_task SET created_by='alice' WHERE task_id='t1'");var fresh=mappings("map-audit");doThrow(new IllegalStateException("audit unavailable")).when(audit).append(any());assertThatThrownBy(()->tx.executeWithoutResult(s->service.apply(boss,fresh))).hasMessageContaining("audit");assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM detection_task WHERE created_user_id IS NOT NULL OR assignee_user_id IS NOT NULL",Integer.class)).isZero();}
    @Test void databaseWallTimeParticipatesInStablePreviewWithoutBeingRewritten(){
        jdbc.update("UPDATE detection_task SET updated_at='2025-01-02 03:04:05' WHERE task_id='t1'");
        var original=jdbc.queryForMap("SELECT * FROM detection_task WHERE task_id='t1'");
        var first=preview();
        assertThat(first).hasSize(2).allSatisfy(row->{
            assertThat(row.get("snapshot").toString()).matches("[a-f0-9]{64}");
            assertThat(row.get("taskUpdatedAt")).isEqualTo("2025-01-02T03:04:05+08:00");
        });
        assertThat(preview()).isEqualTo(first);
        var stale=mappings("map-walltime");
        assertThat(jdbc.queryForMap("SELECT * FROM detection_task WHERE task_id='t1'")).isEqualTo(original);
        jdbc.update("UPDATE detection_task SET updated_at='2025-01-02 03:04:06' WHERE task_id='t1'");
        var changed=jdbc.queryForMap("SELECT * FROM detection_task WHERE task_id='t1'");
        assertThat(preview()).hasSize(2).allSatisfy(row->{
            assertThat(row.get("snapshot")).isNotEqualTo(first.get(0).get("snapshot"));
            assertThat(row.get("taskUpdatedAt")).isEqualTo("2025-01-02T03:04:06+08:00");
        });
        assertThatThrownBy(()->tx.executeWithoutResult(s->service.apply(boss,stale))).hasMessageContaining("已变化");
        assertThat(jdbc.queryForMap("SELECT * FROM detection_task WHERE task_id='t1'")).isEqualTo(changed);
        assertThat(jdbc.queryForObject("SELECT revision FROM runtime_state WHERE namespace='DETECTION_IDENTITY_CONTROL' AND owner_id=0 AND scope_key='1'",Long.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='DETECTION_IDENTITY_MAP_BATCH'",Integer.class)).isZero();
        verifyNoInteractions(audit);
    }
    @Test void reusedRequestWithDifferentMappingsIsRejected(){var first=mappings("map-1");tx.executeWithoutResult(s->service.apply(boss,first));assertThatThrownBy(()->tx.executeWithoutResult(s->service.apply(boss,new DetectionIdentityService.Apply("map-1",List.of(first.mappings().get(0)),first.revision(),true)))).hasMessageContaining("编号冲突");}
    @Test void activationIsIdempotentAndCannotReuseAnotherCommandRequest(){
        tx.executeWithoutResult(s->service.apply(boss,mappings("map-before-activate")));
        tx.executeWithoutResult(s->service.activate(boss,1,"activate-once"));
        tx.executeWithoutResult(s->service.activate(boss,1,"activate-once"));
        assertThat(jdbc.queryForObject("SELECT revision FROM runtime_state WHERE namespace='DETECTION_IDENTITY_CONTROL' AND owner_id=0 AND scope_key='1'",Long.class)).isEqualTo(2);
        assertThatThrownBy(()->tx.executeWithoutResult(s->service.activate(boss,1,"map-before-activate"))).hasMessageContaining("编号冲突");
        assertThatThrownBy(()->tx.executeWithoutResult(s->service.activate(boss,0,"stale-activate"))).hasMessageContaining("模式已变化");
    }
    @Test void missingAssignmentSnapshotCannotBeTreatedAsCompletedBackfill(){
        jdbc.update("UPDATE detection_task SET created_user_id=2,assignee_user_id=2,assignee_identity_name=NULL");
        assertThatThrownBy(()->tx.executeWithoutResult(s->service.activate(boss,0,"activate-incomplete"))).hasMessageContaining("未完成映射");
    }
}
