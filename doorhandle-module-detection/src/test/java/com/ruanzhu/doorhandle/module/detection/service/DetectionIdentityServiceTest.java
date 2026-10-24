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

class DetectionIdentityServiceTest {
    JdbcTemplate jdbc;BusinessAccountLookupApi accounts;BusinessUserDirectory users;OperationsAuditApi audit;DetectionIdentityService service;TransactionTemplate tx;
    AgentActor boss=new AgentActor(1,"boss",AgentActor.Role.SUPERVISOR),alice=new AgentActor(2,"alice",AgentActor.Role.INSPECTOR);
    @BeforeEach void setup(){
        var source=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa","");jdbc=new JdbcTemplate(source);tx=new TransactionTemplate(new DataSourceTransactionManager(source));
        jdbc.execute("CREATE TABLE detection_task(task_id VARCHAR(128) PRIMARY KEY,created_by VARCHAR(64),assignee VARCHAR(64),reviewer VARCHAR(64),disposition_operator VARCHAR(64),rework_operator VARCHAR(64))");
        for(String role:List.of("created","assignee","reviewer","disposition","rework")){jdbc.execute("ALTER TABLE detection_task ADD "+role+"_user_id BIGINT");jdbc.execute("ALTER TABLE detection_task ADD "+role+"_identity_name VARCHAR(64)");}
        jdbc.execute("CREATE TABLE detection_identity_control(control_id INT PRIMARY KEY,mode VARCHAR(16),revision BIGINT)");jdbc.update("INSERT INTO detection_identity_control VALUES(1,'PREVIEW',0)");
        jdbc.execute("CREATE TABLE detection_identity_command(request_id VARCHAR(128) PRIMARY KEY,actor_user_id BIGINT,request_sha256 VARCHAR(64),result_json VARCHAR(1000),created_at TIMESTAMP)");
        accounts=mock(BusinessAccountLookupApi.class);users=mock(BusinessUserDirectory.class);audit=mock(OperationsAuditApi.class);when(accounts.findExactUserId("alice")).thenReturn(2L);when(accounts.findExactUserId("orphan")).thenReturn(null);when(accounts.username(2)).thenReturn("alice");when(users.current(1,"boss")).thenReturn(new BusinessUserDirectory.Identity(1,"boss",true));when(users.current(2,"alice")).thenReturn(new BusinessUserDirectory.Identity(2,"alice",false));service=new DetectionIdentityService(jdbc,accounts,users,audit,new ObjectMapper());jdbc.update("INSERT INTO detection_task(task_id,created_by,assignee) VALUES('t1','alice','orphan')");
    }
    @SuppressWarnings("unchecked") List<Map<String,Object>> preview(){return (List<Map<String,Object>>)service.preview(boss,"",100).get("records");}
    DetectionIdentityService.Apply mappings(String request){return new DetectionIdentityService.Apply(request,preview().stream().map(row->new DetectionIdentityService.Mapping((String)row.get("taskId"),(String)row.get("role"),(String)row.get("expectedName"),(String)row.get("snapshot"),2L)).toList());}
    @Test void unmappedTasksCannotActivateAndPreviewDoesNotGuessUnknownAccounts(){assertThat(service.active()).isFalse();assertThat(preview()).anyMatch(row->row.get("expectedName").equals("orphan")&&row.get("suggestedUserId")==null);assertThatThrownBy(()->service.activate(boss,0,"activate")).hasMessageContaining("未完成映射");assertThatThrownBy(()->service.preview(alice,"",10)).isInstanceOf(SecurityException.class);}
    @Test void confirmedStableIdsKeepOwnershipWhenAnAccountNameIsReusedAndLegacyAssignmentChangesAreDenied(){var request=mappings("map-1");tx.executeWithoutResult(s->service.apply(boss,request));tx.executeWithoutResult(s->service.activate(boss,0,"activate"));assertThat(service.active()).isTrue();assertThat(service.canAccess("t1",2)).isTrue();when(accounts.findExactUserId("alice")).thenReturn(99L);assertThat(service.canAccess("t1",99)).isFalse();jdbc.update("UPDATE detection_task SET created_user_id=77,assignee='legacy-other' WHERE task_id='t1'");assertThat(service.canAccess("t1",2)).isFalse();assertThat(service.apply(boss,request)).containsEntry("replayed",true);}
    @Test void stalePreviewAndAuditFailureCannotPartiallyChangeOwnership(){var stale=mappings("map-stale");jdbc.update("UPDATE detection_task SET created_by='changed' WHERE task_id='t1'");assertThatThrownBy(()->tx.executeWithoutResult(s->service.apply(boss,stale))).hasMessageContaining("已变化");jdbc.update("UPDATE detection_task SET created_by='alice' WHERE task_id='t1'");var fresh=mappings("map-audit");doThrow(new IllegalStateException("audit unavailable")).when(audit).append(any());assertThatThrownBy(()->tx.executeWithoutResult(s->service.apply(boss,fresh))).hasMessageContaining("audit");assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM detection_task WHERE created_user_id IS NOT NULL OR assignee_user_id IS NOT NULL",Integer.class)).isZero();}
    @Test void reusedRequestWithDifferentMappingsIsRejected(){var first=mappings("map-1");tx.executeWithoutResult(s->service.apply(boss,first));assertThatThrownBy(()->tx.executeWithoutResult(s->service.apply(boss,new DetectionIdentityService.Apply("map-1",List.of(first.mappings().get(0)))))).hasMessageContaining("编号冲突");}
    @Test void activationIsIdempotentAndCannotReuseAnotherCommandRequest(){
        tx.executeWithoutResult(s->service.apply(boss,mappings("map-before-activate")));
        tx.executeWithoutResult(s->service.activate(boss,0,"activate-once"));
        tx.executeWithoutResult(s->service.activate(boss,0,"activate-once"));
        assertThat(jdbc.queryForObject("SELECT revision FROM detection_identity_control",Long.class)).isEqualTo(1);
        assertThatThrownBy(()->tx.executeWithoutResult(s->service.activate(boss,1,"map-before-activate"))).hasMessageContaining("编号冲突");
        assertThatThrownBy(()->tx.executeWithoutResult(s->service.activate(boss,0,"stale-activate"))).hasMessageContaining("模式已变化");
    }
    @Test void missingAssignmentSnapshotCannotBeTreatedAsCompletedBackfill(){
        jdbc.update("UPDATE detection_task SET created_user_id=2,assignee_user_id=2,assignee_identity_name=NULL");
        assertThatThrownBy(()->tx.executeWithoutResult(s->service.activate(boss,0,"activate-incomplete"))).hasMessageContaining("未完成映射");
    }
}
