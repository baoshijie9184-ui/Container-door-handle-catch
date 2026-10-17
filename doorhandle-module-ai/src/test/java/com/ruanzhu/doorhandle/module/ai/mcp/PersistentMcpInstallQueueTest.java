package com.ruanzhu.doorhandle.module.ai.mcp;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.awaitility.Awaitility.await;

@Timeout(15)
class PersistentMcpInstallQueueTest {
    @TempDir Path root;
    final AgentActor alice=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR),bob=new AgentActor(2,"bob",AgentActor.Role.INSPECTOR);
    JdbcTemplate jdbc;BusinessUserDirectory users;FetchMcpRuntime runtime;LocalMcpService service;
    final List<LocalMcpService> services=new ArrayList<>();
    @BeforeEach void setup()throws Exception{
        var source=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa","");jdbc=new JdbcTemplate(source);
        for(String file:List.of("migration-V25-local-mcp.sql","migration-V34-mcp-install-queue.sql")){
            String ddl=Files.readString(Path.of("../sql/mysql",file)).replace(" JSON "," TEXT ").replace(" ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin","").replaceAll("(?m)^\\s*(?:UNIQUE )?KEY .*\\n","").replaceAll(",\\s*\\)","\n)");
            for(String sql:ddl.split(";"))if(!sql.isBlank())jdbc.execute(sql);
        }
        users=mock(BusinessUserDirectory.class);for(var actor:List.of(alice,bob))when(users.current(actor.userId(),actor.username())).thenReturn(new BusinessUserDirectory.Identity(actor.userId(),actor.username(),false));
        runtime=mock(FetchMcpRuntime.class);when(runtime.installationIdentity()).thenReturn("a".repeat(64));when(runtime.install(any())).thenReturn(Map.of("version",FetchMcpRuntime.VERSION));
        service=create();
    }
    LocalMcpService create(){var properties=new AgentScopeProperties();properties.setWorkspace(root.toString());var result=new LocalMcpService(jdbc,new DataSourceTransactionManager(jdbc.getDataSource()),new ObjectMapper(),users,properties,runtime,null,new PersistentMcpInstallQueue(jdbc));result.schema();services.add(result);return result;}
    @AfterEach void close(){services.forEach(LocalMcpService::close);}
    int revision(Map<String,Object> view){return ((Number)view.get("revision")).intValue();}
    String phase(){return jdbc.queryForObject("SELECT status FROM agent_mcp_install_job ORDER BY id LIMIT 1",String.class);}
    void completed(LocalMcpService target){await().atMost(Duration.ofSeconds(3)).until(()->"INSTALLED".equals(target.view(alice).get("status")));}

    @Test void pendingJobSurvivesServiceRestartAndKeepsOriginalConsentAndOperation()throws Exception{
        var queued=service.install(alice,0,"request-persist-one",true);String operation=(String)queued.get("operationId");
        assertThat(queued).containsEntry("installQueue","DURABLE").containsEntry("installPhase","QUEUED").containsEntry("enabled",false);verify(runtime,never()).install(any());
        service.install(alice,0,"request-persist-one",true);assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_mcp_install_job",Integer.class)).isEqualTo(1);
        service.close();service.dispatchInstallation();verify(runtime,never()).install(any());
        var restarted=create();restarted.dispatchInstallation();completed(restarted);
        assertThat(restarted.view(alice)).containsEntry("operationId",operation).containsEntry("enabled",false).containsEntry("installPhase","SUCCEEDED");verify(runtime,times(1)).install(any());
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_local_mcp_audit WHERE outcome='DISPATCHED'",Integer.class)).isEqualTo(1);
    }
    @Test void queuedCancellationIsDurableAndCannotBeRecoveredByAnotherService()throws Exception{
        var queued=service.install(alice,0,"request-persist-cancel",true);service.cancelInstallation(alice,revision(queued),(String)queued.get("operationId"),true);
        assertThat(phase()).isEqualTo("CANCELLED");service.close();var restarted=create();restarted.dispatchInstallation();verify(runtime,never()).install(any());
        assertThat(restarted.view(alice)).containsEntry("status","CANCELLED");assertThat(restarted.view(bob)).containsEntry("status","NOT_INSTALLED").containsEntry("installPhase",null);
    }
    @Test void changedRuntimeFailsClosedAndRequiresNewConfirmation()throws Exception{
        service.install(alice,0,"request-persist-change",true);service.close();when(runtime.installationIdentity()).thenReturn("b".repeat(64));var restarted=create();restarted.dispatchInstallation();
        assertThat(restarted.view(alice)).containsEntry("status","ERROR").containsEntry("errorCode","INSTALL_RUNTIME_CHANGED");assertThat(phase()).isEqualTo("FAILED");verify(runtime,never()).install(any());
        var current=restarted.view(alice);assertThatThrownBy(()->restarted.install(alice,revision(current),"request-new-target",false)).hasMessageContaining("许可证");
    }
    @Test void concurrentServicesClaimExactlyOnce()throws Exception{
        var entered=new CountDownLatch(1);var release=new CountDownLatch(1);when(runtime.install(any())).thenAnswer(inv->{entered.countDown();release.await(4,TimeUnit.SECONDS);return Map.of("version",FetchMcpRuntime.VERSION);});
        service.install(alice,0,"request-persist-race",true);var other=create();var executor=Executors.newFixedThreadPool(2);var start=new CountDownLatch(1);
        try{
            var first=executor.submit(()->{start.await();service.dispatchInstallation();return true;});var second=executor.submit(()->{start.await();other.dispatchInstallation();return true;});start.countDown();first.get(3,TimeUnit.SECONDS);second.get(3,TimeUnit.SECONDS);
            assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();assertThat(phase()).isEqualTo("RUNNING");verify(runtime,times(1)).install(any());release.countDown();completed(service);assertThat(phase()).isEqualTo("SUCCEEDED");
        }finally{release.countDown();executor.shutdownNow();}
    }
    @Test void startedJobIsNotReplayedAfterRestartAndExpiredLeaseRequiresNewConsent()throws Exception{
        var entered=new CountDownLatch(1);var interrupted=new CountDownLatch(1);when(runtime.install(any())).thenAnswer(inv->{entered.countDown();try{new CountDownLatch(1).await();}catch(InterruptedException error){interrupted.countDown();throw error;}return Map.of();});
        service.install(alice,0,"request-persist-running",true);service.dispatchInstallation();assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();service.close();assertThat(interrupted.await(2,TimeUnit.SECONDS)).isTrue();
        var restarted=create();restarted.dispatchInstallation();assertThat(phase()).isEqualTo("RUNNING");verify(runtime,times(1)).install(any());
        jdbc.update("UPDATE agent_local_mcp SET lease_expires_at=?",LocalDateTime.now().minusDays(1));restarted.expire();
        assertThat(restarted.view(alice)).containsEntry("status","ERROR").containsEntry("errorCode","INSTALL_LEASE_EXPIRED");assertThat(phase()).isEqualTo("EXPIRED");
        var expired=restarted.view(alice);assertThatThrownBy(()->restarted.install(alice,revision(expired),"request-persist-retry",false)).hasMessageContaining("许可证");
        doReturn(Map.of("version",FetchMcpRuntime.VERSION)).when(runtime).install(any());restarted.install(alice,revision(expired),"request-persist-retry",true);restarted.dispatchInstallation();completed(restarted);verify(runtime,times(2)).install(any());
    }
    @Test void lostWorkerTokenFencesLateSuccessEvenBeforeExpirySweep()throws Exception{
        var entered=new CountDownLatch(1);var release=new CountDownLatch(1);when(runtime.install(any())).thenAnswer(inv->{entered.countDown();release.await(4,TimeUnit.SECONDS);return Map.of("version",FetchMcpRuntime.VERSION);});
        try{
            service.install(alice,0,"request-persist-token",true);service.dispatchInstallation();assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();jdbc.update("UPDATE agent_mcp_install_job SET worker_token='different-worker'");release.countDown();
            var executor=(ThreadPoolExecutor)org.springframework.test.util.ReflectionTestUtils.getField(service,"jobs");executor.submit(()->{}).get(3,TimeUnit.SECONDS);
            assertThat(service.view(alice)).containsEntry("status","INSTALLING").containsEntry("enabled",false);assertThat(phase()).isEqualTo("RUNNING");
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_local_mcp_audit WHERE outcome='SUCCEEDED'",Integer.class)).isZero();
        }finally{release.countDown();}
    }
    @Test void queueInsertFailureRollsBackRegistrationAndConsentAudit()throws Exception{
        jdbc.execute("ALTER TABLE agent_mcp_install_job ADD CONSTRAINT deny_enqueue CHECK(status<>'QUEUED')");
        assertThatThrownBy(()->service.install(alice,0,"request-persist-rollback",true)).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(service.view(alice)).containsEntry("status","NOT_INSTALLED");assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_local_mcp_audit",Integer.class)).isZero();verify(runtime,never()).install(any());
    }
    @Test void dispatchAuditFailureRollsBackClaimBeforeRuntimeStarts()throws Exception{
        service.install(alice,0,"request-persist-audit",true);jdbc.execute("ALTER TABLE agent_local_mcp_audit ADD CONSTRAINT deny_dispatch CHECK(outcome<>'DISPATCHED')");
        assertThatThrownBy(service::dispatchInstallation).isInstanceOf(org.springframework.dao.DataAccessException.class);assertThat(phase()).isEqualTo("QUEUED");
        assertThat(jdbc.queryForObject("SELECT worker_token FROM agent_mcp_install_job",String.class)).isNull();verify(runtime,never()).install(any());
    }
    @Test void cancelAuditFailurePreservesPendingJob(){
        var queued=service.install(alice,0,"request-persist-cancel-audit",true);jdbc.execute("ALTER TABLE agent_local_mcp_audit ADD CONSTRAINT deny_cancel CHECK(action_name<>'CANCEL_INSTALL')");
        assertThatThrownBy(()->service.cancelInstallation(alice,revision(queued),(String)queued.get("operationId"),true)).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(phase()).isEqualTo("QUEUED");assertThat(service.view(alice)).containsEntry("status","INSTALLING");
    }
    @Test void accountIsRecheckedBeforePersistedJobExecutes()throws Exception{
        service.install(alice,0,"request-persist-account",true);when(users.current(1,"alice")).thenThrow(new SecurityException("PRIVATE_ACCOUNT_ERROR"));service.dispatchInstallation();
        await().atMost(Duration.ofSeconds(3)).until(()->"FAILED".equals(phase()));verify(runtime,never()).install(any());
        assertThat(jdbc.queryForObject("SELECT error_code FROM agent_local_mcp",String.class)).isEqualTo("INSTALL_FAILED");
    }
    @Test void expiredPendingHeadDoesNotPreventAnotherUsersTaskFromStarting()throws Exception{
        service.install(alice,0,"request-expired-head",true);service.install(bob,0,"request-valid-next",true);
        jdbc.update("UPDATE agent_local_mcp SET lease_expires_at=? WHERE owner_user_id=1",LocalDateTime.now().minusDays(1));service.dispatchInstallation();
        assertThat(service.view(alice)).containsEntry("status","ERROR").containsEntry("errorCode","INSTALL_LEASE_EXPIRED");service.dispatchInstallation();
        await().atMost(Duration.ofSeconds(3)).until(()->"INSTALLED".equals(service.view(bob).get("status")));verify(runtime,times(1)).install(any());
    }
    @Test void expiredLeaseFencesCompletionBeforeMaintenanceRuns()throws Exception{
        var entered=new CountDownLatch(1);var release=new CountDownLatch(1);when(runtime.install(any())).thenAnswer(inv->{entered.countDown();release.await(4,TimeUnit.SECONDS);return Map.of("version",FetchMcpRuntime.VERSION);});
        try{
            service.install(alice,0,"request-expire-before-write",true);service.dispatchInstallation();assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();
            jdbc.update("UPDATE agent_local_mcp SET lease_expires_at=?",LocalDateTime.now().minusDays(1));release.countDown();
            var executor=(ThreadPoolExecutor)org.springframework.test.util.ReflectionTestUtils.getField(service,"jobs");executor.submit(()->{}).get(3,TimeUnit.SECONDS);
            assertThat(service.view(alice)).containsEntry("status","INSTALLING").containsEntry("enabled",false);assertThat(phase()).isEqualTo("RUNNING");
            service.expire();assertThat(phase()).isEqualTo("EXPIRED");
        }finally{release.countDown();}
    }
    @Test void completionAuditFailureRollsBackSuccessAndMarksBothRecordsFailed()throws Exception{
        service.install(alice,0,"request-completion-audit",true);jdbc.execute("ALTER TABLE agent_local_mcp_audit ADD CONSTRAINT deny_success CHECK(outcome<>'SUCCEEDED')");service.dispatchInstallation();
        await().atMost(Duration.ofSeconds(3)).until(()->"FAILED".equals(phase()));assertThat(service.view(alice)).containsEntry("status","ERROR").containsEntry("manifest",null).containsEntry("enabled",false);verify(runtime,times(1)).install(any());
    }
    @Test void anotherServiceCanRevokeRunningRegistrationAndFenceLateResults()throws Exception{
        var entered=new CountDownLatch(1);var release=new CountDownLatch(1);when(runtime.install(any())).thenAnswer(inv->{entered.countDown();release.await(4,TimeUnit.SECONDS);return Map.of("version",FetchMcpRuntime.VERSION);});
        try{
            service.install(alice,0,"request-remote-cancel",true);service.dispatchInstallation();assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();var other=create();var running=other.view(alice);
            other.cancelInstallation(alice,revision(running),(String)running.get("operationId"),true);assertThat(phase()).isEqualTo("CANCELLED");release.countDown();
            var executor=(ThreadPoolExecutor)org.springframework.test.util.ReflectionTestUtils.getField(service,"jobs");executor.submit(()->{}).get(3,TimeUnit.SECONDS);
            assertThat(service.view(alice)).containsEntry("status","CANCELLED").containsEntry("enabled",false);assertThat(phase()).isEqualTo("CANCELLED");
        }finally{release.countDown();}
    }
    @Test void runtimeIdentityBindsTargetButDoesNotPersistCredentials(){
        var properties=new LocalMcpProperties();properties.setTransport("GATEWAY");properties.setGatewayImage("fixed-image-one");var nativeRuntime=new FetchMcpRuntime(properties,new ObjectMapper());String identity=nativeRuntime.installationIdentity();
        properties.setGatewaySecret("PRIVATE_SECRET");properties.setGatewayKey("PRIVATE_KEY");assertThat(nativeRuntime.installationIdentity()).isEqualTo(identity).matches("[a-f0-9]{64}");
        properties.setGatewayImage("fixed-image-two");assertThat(nativeRuntime.installationIdentity()).isNotEqualTo(identity);assertThat(new LocalMcpProperties().isDurableInstallEnabled()).isFalse();
    }
}
