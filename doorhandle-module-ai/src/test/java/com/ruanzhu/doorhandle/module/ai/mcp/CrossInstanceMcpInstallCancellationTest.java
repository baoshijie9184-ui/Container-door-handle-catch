package com.ruanzhu.doorhandle.module.ai.mcp;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import java.nio.file.Path;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.Map;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;
import static org.awaitility.Awaitility.await;
import static org.mockito.Mockito.*;

@Timeout(15)
class CrossInstanceMcpInstallCancellationTest {
    @TempDir Path root;
    final PersistentMcpInstallQueueTest fixture=new PersistentMcpInstallQueueTest();
    final CountDownLatch entered=new CountDownLatch(1),interrupted=new CountDownLatch(1),release=new CountDownLatch(1);
    @BeforeEach void setup()throws Exception{fixture.root=root;fixture.setup();}
    @AfterEach void close(){release.countDown();fixture.close();}
    void block(boolean ignoreInterrupt)throws Exception{
        when(fixture.runtime.install(any())).thenAnswer(inv->{
            entered.countDown();
            try{release.await();}catch(InterruptedException error){interrupted.countDown();if(!ignoreInterrupt)throw error;release.await(5,TimeUnit.SECONDS);}
            return Map.of("version",FetchMcpRuntime.VERSION);
        });
    }
    Map<String,Object> start(LocalMcpService worker)throws Exception{
        var queued=worker.install(fixture.alice,0,"request-cross-instance",true);worker.dispatchInstallation();
        assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();return queued;
    }
    void cancel(LocalMcpService other){var running=other.view(fixture.alice);other.cancelInstallation(fixture.alice,fixture.revision(running),(String)running.get("operationId"),true);}
    ThreadPoolExecutor executor(LocalMcpService worker){return (ThreadPoolExecutor)org.springframework.test.util.ReflectionTestUtils.getField(worker,"jobs");}
    void drained(LocalMcpService worker)throws Exception{executor(worker).submit(()->{}).get(3,TimeUnit.SECONDS);}
    int successes(){return fixture.jdbc.queryForObject("SELECT COUNT(*) FROM agent_local_mcp_audit WHERE outcome='SUCCEEDED' AND action_name='INSTALL'",Integer.class);}

    @Test void busyWorkerObservesCommittedRemoteCancellationAndInterruptsItsOwnTask()throws Exception{
        block(false);start(fixture.service);var other=fixture.create();cancel(other);
        assertThat(interrupted.getCount()).isEqualTo(1); // 别的实例没有本地句柄，必须由执行节点轮询发现。
        fixture.service.dispatchInstallation();assertThat(interrupted.await(2,TimeUnit.SECONDS)).isTrue();drained(fixture.service);
        assertThat(fixture.phase()).isEqualTo("CANCELLED");assertThat(successes()).isZero();
        assertThat(fixture.jdbc.queryForObject("SELECT COUNT(*) FROM agent_local_mcp_audit WHERE action_name='CANCEL_INSTALL'",Integer.class)).isEqualTo(1);
    }
    @Test void validRunningJobIsNotInterruptedByBusyPolling()throws Exception{
        block(false);var queued=start(fixture.service);fixture.service.dispatchInstallation();fixture.service.dispatchInstallation();
        assertThat(interrupted.getCount()).isEqualTo(1);assertThat(fixture.phase()).isEqualTo("RUNNING");
        String token=fixture.jdbc.queryForObject("SELECT worker_token FROM agent_mcp_install_job",String.class);
        var queue=new PersistentMcpInstallQueue(fixture.jdbc);String operation=(String)queued.get("operationId");
        assertThat(queue.executable(fixture.alice.userId(),operation,token)).isTrue();
        assertThat(queue.executable(fixture.bob.userId(),operation,token)).isFalse();
        assertThat(queue.executable(fixture.alice.userId(),operation,null)).isFalse();
        release.countDown();fixture.completed(fixture.service);assertThat(successes()).isEqualTo(1);
    }
    @Test void leaseExpiryInterruptsBeforeTheSixtySecondExpirySweep()throws Exception{
        block(false);start(fixture.service);fixture.jdbc.update("UPDATE agent_local_mcp SET lease_expires_at=?",LocalDateTime.now().minusDays(1));
        fixture.service.dispatchInstallation();assertThat(interrupted.await(2,TimeUnit.SECONDS)).isTrue();drained(fixture.service);
        assertThat(fixture.phase()).isEqualTo("RUNNING");assertThat(successes()).isZero();
        fixture.create().expire();assertThat(fixture.phase()).isEqualTo("EXPIRED");
    }
    @Test void changedWorkerTokenInterruptsWithoutOverwritingTheOtherWorkersRecord()throws Exception{
        block(false);start(fixture.service);fixture.jdbc.update("UPDATE agent_mcp_install_job SET worker_token='new-worker-token'");
        fixture.service.dispatchInstallation();assertThat(interrupted.await(2,TimeUnit.SECONDS)).isTrue();drained(fixture.service);
        assertThat(fixture.phase()).isEqualTo("RUNNING");assertThat(successes()).isZero();
        assertThat(fixture.jdbc.queryForObject("SELECT worker_token FROM agent_mcp_install_job",String.class)).isEqualTo("new-worker-token");
    }
    @Test void cancelAuditRollbackDoesNotInterruptTheStillAuthorizedWorker()throws Exception{
        block(false);start(fixture.service);var other=fixture.create();
        fixture.jdbc.execute("ALTER TABLE agent_local_mcp_audit ADD CONSTRAINT deny_cancel CHECK(action_name<>'CANCEL_INSTALL')");
        assertThatThrownBy(()->cancel(other)).isInstanceOf(org.springframework.dao.DataAccessException.class);
        fixture.service.dispatchInstallation();assertThat(interrupted.getCount()).isEqualTo(1);assertThat(fixture.phase()).isEqualTo("RUNNING");
        release.countDown();fixture.completed(fixture.service);assertThat(successes()).isEqualTo(1);
    }
    @Test void cancellingAnotherUsersQueuedJobDoesNotInterruptTheActiveUser()throws Exception{
        block(false);start(fixture.service);var other=fixture.create();var bob=other.install(fixture.bob,0,"request-other-user",true);
        other.cancelInstallation(fixture.bob,fixture.revision(bob),(String)bob.get("operationId"),true);
        fixture.service.dispatchInstallation();assertThat(interrupted.getCount()).isEqualTo(1);
        release.countDown();fixture.completed(fixture.service);assertThat(other.view(fixture.bob)).containsEntry("status","CANCELLED");
    }
    @Test void cancelledFutureDoesNotFreeTheExecutionSlotUntilThePhysicalWorkerReturns()throws Exception{
        block(true);start(fixture.service);var other=fixture.create();cancel(other);
        other.install(fixture.bob,0,"request-next-user",true);fixture.service.dispatchInstallation();assertThat(interrupted.await(2,TimeUnit.SECONDS)).isTrue();
        fixture.service.dispatchInstallation();assertThat(executor(fixture.service).getActiveCount()).isEqualTo(1);
        assertThat(other.view(fixture.bob)).containsEntry("installPhase","QUEUED");verify(fixture.runtime,times(1)).install(any());
        release.countDown();drained(fixture.service);fixture.service.dispatchInstallation();
        await().atMost(Duration.ofSeconds(3)).until(()->"INSTALLED".equals(other.view(fixture.bob).get("status")));
        assertThat(fixture.service.view(fixture.alice)).containsEntry("status","CANCELLED");assertThat(successes()).isEqualTo(1);
    }
    @Test void anOldRemoteCancellationCannotAffectANewConfirmedInstallation()throws Exception{
        block(true);start(fixture.service);var other=fixture.create();cancel(other);
        var cancelled=other.view(fixture.alice);var next=other.install(fixture.alice,fixture.revision(cancelled),"request-new-operation",true);
        fixture.service.dispatchInstallation();assertThat(interrupted.await(2,TimeUnit.SECONDS)).isTrue();release.countDown();drained(fixture.service);
        other.dispatchInstallation();fixture.completed(other);
        assertThat(other.view(fixture.alice)).containsEntry("operationId",next.get("operationId")).containsEntry("installPhase","SUCCEEDED");assertThat(successes()).isEqualTo(1);
    }
    @Test void unavailableControlReadStopsLateSuccessWithoutFabricatingCancellationOrReplaying()throws Exception{
        var queue=spy(new PersistentMcpInstallQueue(fixture.jdbc));var properties=new AgentScopeProperties();properties.setWorkspace(root.toString());
        var worker=new LocalMcpService(fixture.jdbc,new DataSourceTransactionManager(fixture.jdbc.getDataSource()),new ObjectMapper(),fixture.users,properties,fixture.runtime,null,queue);
        worker.schema();fixture.services.add(worker);block(true);start(worker);
        doThrow(new org.springframework.dao.DataAccessResourceFailureException("PRIVATE_CONNECTION_DETAILS")).when(queue).executable(anyLong(),anyString(),anyString());
        worker.dispatchInstallation();assertThat(interrupted.await(2,TimeUnit.SECONDS)).isTrue();release.countDown();drained(worker);
        assertThat(worker.view(fixture.alice)).containsEntry("status","INSTALLING").containsEntry("enabled",false);
        assertThat(fixture.phase()).isEqualTo("RUNNING");assertThat(successes()).isZero();
        worker.dispatchInstallation();verify(fixture.runtime,times(1)).install(any());
        fixture.jdbc.update("UPDATE agent_local_mcp SET lease_expires_at=?",LocalDateTime.now().minusDays(1));worker.expire();assertThat(fixture.phase()).isEqualTo("EXPIRED");
    }
}
