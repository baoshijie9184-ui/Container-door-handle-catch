package com.ruanzhu.doorhandle.module.ai.action;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.config.AgentActionProperties;
import com.ruanzhu.doorhandle.module.ai.journal.AgentJournal;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class AgentActionServiceTest {
    private final AgentActor boss=new AgentActor(1,"boss",AgentActor.Role.SUPERVISOR),other=new AgentActor(2,"other",AgentActor.Role.SUPERVISOR),employee=new AgentActor(3,"alice",AgentActor.Role.INSPECTOR);
    private JdbcTemplate jdbc;private AgentActionService actions;private DetectionAssignmentApi assignments;private AgentActionProperties settings;
    private final DetectionAssignmentApi.Command command=new DetectionAssignmentApi.Command("task-1","质检站 A","alice",null,"检查任务");
    @BeforeEach void setup() throws Exception {
        var source=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa","");
        jdbc=new JdbcTemplate(source);
        var ddl=Files.readString(Path.of("src/main/resources/db/migration-V19-agent-confirmation.sql"))
                .replace(" COLLATE utf8mb4_bin","").replace(" ENGINE=InnoDB DEFAULT CHARSET=utf8mb4","").replace(" JSON"," VARCHAR(8192)");
        for(var sql:ddl.split(";"))if(!sql.isBlank())jdbc.execute(sql);
        jdbc.execute("CREATE TABLE agent_run(run_id VARCHAR(128) PRIMARY KEY,user_id BIGINT,session_id VARCHAR(128),status VARCHAR(24))");
        jdbc.update("INSERT INTO agent_run VALUES('run-1',1,'session-1','COMPLETED')");
        jdbc.execute("CREATE TABLE fixture_task(id VARCHAR(128) PRIMARY KEY,writes INT NOT NULL,resource_version VARCHAR(64))");
        jdbc.update("INSERT INTO fixture_task VALUES('task-1',0,'revision-1')");
        assignments=mock(DetectionAssignmentApi.class);
        when(assignments.preview(any(),any())).thenAnswer(invocation->new DetectionAssignmentApi.Preview(invocation.getArgument(1),new DetectionAssignmentApi.Values(null,null,null,null,"DETECTED"),jdbc.queryForObject("SELECT resource_version FROM fixture_task",String.class)));
        when(assignments.apply(any(),any(),anyString())).thenAnswer(invocation->{
            jdbc.update("UPDATE fixture_task SET writes=writes+1");
            return new DetectionAssignmentApi.Applied("task-1",new DetectionAssignmentApi.Values("质检站 A","alice",null,"检查任务","REVIEWING"));
        });
        var journal=mock(AgentJournal.class);when(journal.enabled()).thenReturn(true);
        settings=new AgentActionProperties();settings.setEnabled(true);
        actions=new AgentActionService(jdbc,new DataSourceTransactionManager(source),new ObjectMapper(),journal,assignments,settings);actions.verifySchema();
    }
    private AgentActionService.View propose(){return actions.propose(boss,"run-1","call-1",command);}
    private int writes(){return jdbc.queryForObject("SELECT writes FROM fixture_task",Integer.class);}
    @Test void proposalIsDurableAndNeverExecutesTheBusinessWrite(){
        var action=propose();assertThat(action.status()).isEqualTo("PENDING");assertThat(writes()).isZero();
        assertThat(actions.list(boss,"session-1",null,10)).extracting(AgentActionService.View::actionId).containsExactly(action.actionId());
        assertThat(actions.audit(boss,action.actionId())).extracting(AgentActionService.Audit::eventType).containsExactly("CONFIRMATION_CREATED");
        verify(assignments,never()).apply(any(),any(),any());
    }
    @Test void approvalExecutesOnceAndRepeatedOrOppositeDecisionReturnsOriginalResult(){
        var a=propose();var done=actions.decide(boss,a.actionId(),1,"APPROVE");
        assertThat(done.status()).isEqualTo("SUCCEEDED");assertThat(done.result().after().assignee()).isEqualTo("alice");
        assertThat(actions.decide(boss,a.actionId(),1,"APPROVE")).isEqualTo(done);
        assertThat(actions.decide(boss,a.actionId(),1,"REJECT")).isEqualTo(done);assertThat(writes()).isEqualTo(1);
        assertThat(actions.audit(boss,a.actionId())).extracting(AgentActionService.Audit::eventType).containsExactly("CONFIRMATION_CREATED","AUTHORIZATION_ALLOWED","CONFIRMATION_DECIDED","TOOL_EXECUTION_STARTED","BUSINESS_CHANGED","TOOL_EXECUTION_COMPLETED");
    }
    @Test void rejectCancelAndExpirationNeverWrite(){
        var a=propose();assertThat(actions.decide(boss,a.actionId(),1,"REJECT").status()).isEqualTo("REJECTED");
        jdbc.update("INSERT INTO agent_run VALUES('run-2',1,'session-2','COMPLETED')");
        var b=actions.propose(boss,"run-2",null,command);assertThat(actions.decide(boss,b.actionId(),1,"CANCEL").status()).isEqualTo("CANCELLED");
        jdbc.update("INSERT INTO agent_run VALUES('run-3',1,'session-3','COMPLETED')");
        var c=actions.propose(boss,"run-3",null,command);jdbc.update("UPDATE agent_pending_action SET expires_at=DATEADD('MINUTE',-1,CURRENT_TIMESTAMP) WHERE action_id=?",c.actionId());
        assertThat(actions.decide(boss,c.actionId(),1,"APPROVE").status()).isEqualTo("EXPIRED");assertThat(writes()).isZero();
    }
    @Test void otherAccountCannotReadConfirmCancelOrReadAudit(){
        var a=propose();assertThat(actions.list(other,null,null,10)).isEmpty();
        assertThatThrownBy(()->actions.get(other,a.actionId())).hasMessageContaining("404");
        assertThatThrownBy(()->actions.audit(other,a.actionId())).hasMessageContaining("404");
        assertThatThrownBy(()->actions.decide(other,a.actionId(),1,"APPROVE")).hasMessageContaining("404");
        assertThatThrownBy(()->actions.decide(other,a.actionId(),1,"CANCEL")).hasMessageContaining("404");assertThat(writes()).isZero();
    }
    @Test void staffCannotProposeAndRevokedRoleInvalidatesPending(){
        assertThatThrownBy(()->actions.propose(employee,"run-1",null,command)).isInstanceOf(SecurityException.class);
        var a=propose();var revoked=new AgentActor(boss.userId(),boss.username(),AgentActor.Role.INSPECTOR);
        assertThat(actions.decide(revoked,a.actionId(),1,"APPROVE").reasonCode()).isEqualTo("ROLE_REVOKED");assertThat(writes()).isZero();
    }
    @Test void proposalIdempotencyAndChangedParametersInvalidateOldDraft(){
        var a=propose();assertThat(propose().actionId()).isEqualTo(a.actionId());
        var b=actions.propose(boss,"run-1","call-2",new DetectionAssignmentApi.Command("task-1","另一个站点","alice",null,"新参数"));
        assertThat(b.actionId()).isNotEqualTo(a.actionId());assertThat(actions.get(boss,a.actionId()).reasonCode()).isEqualTo("PARAMETERS_SUPERSEDED");
        assertThat(actions.decide(boss,a.actionId(),1,"APPROVE").status()).isEqualTo("INVALIDATED");assertThat(writes()).isZero();
    }
    @Test void resourceVersionOrPolicyChangeInvalidatesWithoutWrite(){
        var a=propose();jdbc.update("UPDATE fixture_task SET resource_version='revision-2'");
        assertThat(actions.decide(boss,a.actionId(),1,"APPROVE").reasonCode()).isEqualTo("RESOURCE_CHANGED");
        jdbc.update("INSERT INTO agent_run VALUES('run-2',1,'session-2','COMPLETED')");
        var b=actions.propose(boss,"run-2",null,command);jdbc.update("UPDATE agent_pending_action SET policy_version='retired' WHERE action_id=?",b.actionId());
        assertThat(actions.decide(boss,b.actionId(),1,"APPROVE").reasonCode()).isEqualTo("POLICY_CHANGED");assertThat(writes()).isZero();
    }
    @Test void canceledOriginAndStaleClientVersionDoNotExecute(){
        var a=propose();assertThatThrownBy(()->actions.decide(boss,a.actionId(),9,"APPROVE")).hasMessageContaining("409");
        jdbc.update("UPDATE agent_run SET status='CANCELLED'");assertThat(actions.decide(boss,a.actionId(),1,"APPROVE").reasonCode()).isEqualTo("ORIGIN_RUN_TERMINATED");assertThat(writes()).isZero();
    }
    @Test void auditFailureRollsBackAlreadyAppliedBusinessWrite(){
        var a=propose();jdbc.execute("ALTER TABLE agent_action_audit ADD CONSTRAINT fixture_fail_audit CHECK(event_type<>'TOOL_EXECUTION_COMPLETED')");
        assertThatThrownBy(()->actions.decide(boss,a.actionId(),1,"APPROVE")).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(writes()).isZero();assertThat(actions.get(boss,a.actionId()).status()).isEqualTo("PENDING");
        assertThat(actions.audit(boss,a.actionId())).hasSize(1);
    }
    @Test void tamperedStoredArgumentsAndBusinessFailureCannotProduceSuccess(){
        var a=propose();jdbc.update("UPDATE agent_pending_action SET command_json=REPLACE(command_json,'alice','evil') WHERE action_id=?",a.actionId());
        assertThatThrownBy(()->actions.decide(boss,a.actionId(),1,"APPROVE")).isInstanceOf(IllegalStateException.class);assertThat(writes()).isZero();
    }
    @Test void concurrentApprovalsProduceOneBusinessWrite() throws Exception {
        var a=propose();var pool=Executors.newFixedThreadPool(2);var barrier=new CyclicBarrier(2);
        try {Callable<String> confirm=()->{barrier.await();return actions.decide(boss,a.actionId(),1,"APPROVE").status();};
            var first=pool.submit(confirm);var second=pool.submit(confirm);assertThat(first.get(10,TimeUnit.SECONDS)).isEqualTo("SUCCEEDED");assertThat(second.get(10,TimeUnit.SECONDS)).isEqualTo("SUCCEEDED");assertThat(writes()).isEqualTo(1);
        } finally {pool.shutdownNow();}
    }
    @Test void disabledFeatureAndInvalidInputFailBeforeCreatingDrafts(){
        settings.setEnabled(false);assertThatThrownBy(this::propose).hasMessageContaining("503");
        settings.setEnabled(true);assertThatThrownBy(()->actions.decide(boss,"invalid/id",1,"APPROVE")).hasMessageContaining("400");
        assertThatThrownBy(()->actions.decide(boss,"some-id",1,"invented")).hasMessageContaining("400");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_pending_action",Integer.class)).isZero();
    }
    @Test void dottedUsernameSessionsCanReadOwnActionsWithoutExpandingAccountOrOperationPermissions(){
        String session="sess_supervisor.demo_abc123";jdbc.update("UPDATE agent_run SET session_id=? WHERE run_id='run-1'",session);var pending=propose();
        assertThat(actions.list(boss,session,null,50)).extracting(AgentActionService.View::actionId).containsExactly(pending.actionId());
        assertThat(actions.list(other,session,null,50)).isEmpty();
        for(String invalid:List.of("../secret","sess/user","sess?user=2"))assertThatThrownBy(()->actions.list(boss,invalid,null,50)).hasMessageContaining("400");
        assertThatThrownBy(()->actions.get(boss,"action.with.dot")).hasMessageContaining("400");assertThat(writes()).isZero();
    }
    private DetectionExecutionApi retryFixture(){
        var execution=mock(DetectionExecutionApi.class);
        when(execution.previewRetry(any(),eq("task-1"))).thenReturn(retryPreview("a".repeat(64)));
        when(execution.retry(any(),anyString(),anyString(),any())).thenAnswer(invocation->{
            assertThat(org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive()).isTrue();
            jdbc.update("UPDATE fixture_task SET writes=writes+1");
            return new DetectionExecutionApi.Receipt("command-1","RETRY","task-1","dispatch-new","QUEUED");
        });
        actions.setDetectionExecution(execution);return execution;
    }
    private DetectionExecutionApi.RetryPreview retryPreview(String version){
        return new DetectionExecutionApi.RetryPreview("task-1",version,"FAILED","FAILED","dispatch-old",12,new java.math.BigDecimal("0.5"),2,"清空当前检测结果与复核、处置状态；不会自动放行");
    }
    @Test void employeeRetryProposalNeedsExplicitApprovalAndReusesOneCommand(){
        var execution=retryFixture();jdbc.update("INSERT INTO agent_run VALUES('employee-run',3,'employee-session','COMPLETED')");
        var pending=actions.proposeRetry(employee,"employee-run","retry-call","task-1");
        assertThat(pending.command()).isNull();assertThat(pending.retry().imageCount()).isEqualTo(2);assertThat(pending.status()).isEqualTo("PENDING");
        assertThat(writes()).isZero();verify(execution,never()).retry(any(),any(),any(),any());
        assertThat(actions.proposeRetry(employee,"employee-run","retry-call","task-1").actionId()).isEqualTo(pending.actionId());
        var done=actions.decide(employee,pending.actionId(),1,"APPROVE");
        assertThat(done.execution().status()).isEqualTo("QUEUED");assertThat(done.status()).isEqualTo("SUCCEEDED");
        assertThat(actions.decide(employee,pending.actionId(),1,"APPROVE")).isEqualTo(done);assertThat(writes()).isEqualTo(1);
        verify(execution).retry(eq(employee),eq(pending.actionId()),eq(pending.actionId()),eq(new DetectionExecutionApi.RetryApproval("task-1","a".repeat(64))));
        assertThat(actions.audit(employee,pending.actionId())).hasSize(6);verifyNoInteractions(assignments);
    }
    @Test void retrySnapshotChangeInvalidatesRatherThanApprovingChangedParameters(){
        var execution=retryFixture();var pending=actions.proposeRetry(boss,"run-1","retry-call","task-1");
        when(execution.previewRetry(boss,"task-1")).thenReturn(retryPreview("b".repeat(64)));
        assertThat(actions.decide(boss,pending.actionId(),1,"APPROVE").reasonCode()).isEqualTo("RESOURCE_CHANGED");
        assertThat(writes()).isZero();verify(execution,never()).retry(any(),any(),any(),any());
    }
    @Test void unknownRetryResultAndPermissionRevocationCannotExecute(){
        var execution=retryFixture();var pending=actions.proposeRetry(boss,"run-1","retry-call","task-1");
        when(execution.previewRetry(boss,"task-1")).thenThrow(new DetectionExecutionApi.NeedsReview());
        assertThat(actions.decide(boss,pending.actionId(),1,"APPROVE").reasonCode()).isEqualTo("EXECUTION_NEEDS_REVIEW");
        reset(execution);when(execution.previewRetry(any(),any())).thenReturn(retryPreview("b".repeat(64)));
        var next=actions.proposeRetry(boss,"run-1","retry-call-2","task-1");
        when(execution.previewRetry(any(),any())).thenThrow(new SecurityException());
        assertThat(actions.decide(boss,next.actionId(),1,"APPROVE").reasonCode()).isEqualTo("ROLE_REVOKED");assertThat(writes()).isZero();
    }
    @Test void retryAuditFailureRollsBackDomainWriteAndKeepsPending(){
        retryFixture();var pending=actions.proposeRetry(boss,"run-1","retry-call","task-1");
        jdbc.execute("ALTER TABLE agent_action_audit ADD CONSTRAINT fixture_retry_fail_audit CHECK(event_type<>'TOOL_EXECUTION_COMPLETED')");
        assertThatThrownBy(()->actions.decide(boss,pending.actionId(),1,"APPROVE")).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(writes()).isZero();assertThat(actions.get(boss,pending.actionId()).status()).isEqualTo("PENDING");assertThat(actions.audit(boss,pending.actionId())).hasSize(1);
    }
    @Test void retryUnknownCommandFailureIsNotConvertedToSuccessOrRepeatedByService(){
        var execution=retryFixture();var pending=actions.proposeRetry(boss,"run-1","retry-call","task-1");
        when(execution.retry(any(),any(),any(),any())).thenAnswer(inv->{jdbc.update("UPDATE fixture_task SET writes=writes+1");throw new IllegalStateException("injected uncertain commit");});
        assertThatThrownBy(()->actions.decide(boss,pending.actionId(),1,"APPROVE")).hasMessage("injected uncertain commit");
        assertThat(writes()).isZero();assertThat(actions.get(boss,pending.actionId()).status()).isEqualTo("PENDING");
        verify(execution).retry(any(),eq(pending.actionId()),eq(pending.actionId()),any());
    }
    @Test void retryTamperedSnapshotIsRefusedAndStaleVersionCannotApprove(){
        var execution=retryFixture();var pending=actions.proposeRetry(boss,"run-1","retry-call","task-1");
        assertThatThrownBy(()->actions.decide(boss,pending.actionId(),2,"APPROVE")).hasMessageContaining("409");
        jdbc.update("UPDATE agent_pending_action SET before_json=REPLACE(before_json,'0.5','0.9') WHERE action_id=?",pending.actionId());
        assertThatThrownBy(()->actions.decide(boss,pending.actionId(),1,"APPROVE")).isInstanceOf(IllegalStateException.class);
        assertThat(writes()).isZero();verify(execution,never()).retry(any(),any(),any(),any());
    }
    @Test void retryCrossAccountCancelAndTerminatedOriginNeverExecute(){
        var execution=retryFixture();var pending=actions.proposeRetry(boss,"run-1","retry-call","task-1");
        assertThatThrownBy(()->actions.decide(other,pending.actionId(),1,"APPROVE")).hasMessageContaining("404");
        jdbc.update("UPDATE agent_run SET status='CANCELLED'");
        assertThat(actions.decide(boss,pending.actionId(),1,"APPROVE").reasonCode()).isEqualTo("ORIGIN_RUN_TERMINATED");
        jdbc.update("INSERT INTO agent_run VALUES('retry-run-2',1,'session-2','COMPLETED')");
        var next=actions.proposeRetry(boss,"retry-run-2","retry-call","task-1");
        assertThat(actions.decide(boss,next.actionId(),1,"CANCEL").status()).isEqualTo("CANCELLED");
        verify(execution,never()).retry(any(),any(),any(),any());assertThat(writes()).isZero();
    }
    @Test void retryDisabledHasNoFallbackAndOriginalAssignmentStillReadable(){
        var assignment=propose();assertThat(actions.retryEnabled()).isFalse();
        assertThatThrownBy(()->actions.proposeRetry(boss,"run-1","retry-call","task-1")).hasMessageContaining("503");
        assertThat(actions.get(boss,assignment.actionId()).command()).isEqualTo(command);assertThat(writes()).isZero();
    }
    @Test void retryHistoryRechecksBusinessVisibilityInsteadOfLeakingAnOldAuthorizedSnapshot(){
        var execution=retryFixture();var pending=actions.proposeRetry(boss,"run-1","retry-call","task-1");
        assertThat(actions.get(boss,pending.actionId()).retry().taskId()).isEqualTo("task-1");
        doThrow(new SecurityException("access revoked")).when(execution).assertReadable(boss,"task-1");
        assertThatThrownBy(()->actions.get(boss,pending.actionId())).isInstanceOf(SecurityException.class);
        assertThat(actions.list(boss,null,null,50)).isEmpty();
        assertThatThrownBy(()->actions.audit(boss,pending.actionId())).isInstanceOf(SecurityException.class);assertThat(writes()).isZero();
    }
    @Test void simultaneousRetryApprovalsProduceOneWrite() throws Exception {
        retryFixture();var pending=actions.proposeRetry(boss,"run-1","retry-call","task-1");
        var pool=Executors.newFixedThreadPool(2);var gate=new CyclicBarrier(2);
        try {
            Callable<String> confirm=()->{gate.await();return actions.decide(boss,pending.actionId(),1,"APPROVE").status();};
            var first=pool.submit(confirm);var second=pool.submit(confirm);
            assertThat(first.get(10,TimeUnit.SECONDS)).isEqualTo("SUCCEEDED");assertThat(second.get(10,TimeUnit.SECONDS)).isEqualTo("SUCCEEDED");assertThat(writes()).isEqualTo(1);
        } finally {pool.shutdownNow();}
    }
}
