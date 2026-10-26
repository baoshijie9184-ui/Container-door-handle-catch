package com.ruanzhu.doorhandle.module.ai.mcp;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import io.agentscope.core.message.ToolResultBlock;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import reactor.core.publisher.Mono;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.awaitility.Awaitility.await;

@Timeout(15)
class LocalMcpServiceTest {
    @TempDir Path root;
    final AgentActor alice=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR),bob=new AgentActor(2,"bob",AgentActor.Role.INSPECTOR),boss=new AgentActor(3,"boss",AgentActor.Role.SUPERVISOR);
    JdbcTemplate jdbc;LocalMcpService service;FetchMcpRuntime runtime;BusinessUserDirectory users;
    @BeforeEach void setup()throws Exception{var source=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa","");jdbc=new JdbcTemplate(source);
        String ddl=Files.readString(Path.of("../sql/mysql/migration-V25-local-mcp.sql")).replace(" JSON "," TEXT ").replace(" ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin","").replaceAll("(?m)^\\s*(?:UNIQUE )?KEY .*\\n","").replaceAll(",\\s*\\)","\n)");for(String sql:ddl.split(";"))if(!sql.isBlank())jdbc.execute(sql);
        jdbc.execute("CREATE TABLE agent_run(run_id VARCHAR(128),user_id BIGINT,main_agent VARCHAR(64),status VARCHAR(16),lease_expires_at DATETIME)");
        users=mock(BusinessUserDirectory.class);for(var actor:List.of(alice,bob,boss))when(users.current(actor.userId(),actor.username())).thenReturn(new BusinessUserDirectory.Identity(actor.userId(),actor.username(),actor.supervisor()));
        runtime=mock(FetchMcpRuntime.class);when(runtime.writesAllowed()).thenReturn(true);when(runtime.install(any())).thenReturn(Map.of("serverKey","fetch","version",FetchMcpRuntime.VERSION,"packageSha256",FetchMcpRuntime.SHA));
        var session=mock(FetchMcpRuntime.Session.class);when(session.call(any())).thenReturn(Mono.just(ToolResultBlock.text("public page fixture")));when(runtime.open(any(),any())).thenReturn(session);
        var properties=new AgentScopeProperties();properties.setWorkspace(root.toString());service=new LocalMcpService(jdbc,new DataSourceTransactionManager(source),new ObjectMapper(),users,properties,runtime);service.schema();}
    @AfterEach void stop(){service.close();}
    Map<String,Object> installed()throws Exception{service.install(alice,0,"request-install-one",true);await().atMost(Duration.ofSeconds(3)).until(()->"INSTALLED".equals(service.view(alice).get("status")));return service.view(alice);}
    int revision(Map<String,Object> v){return ((Number)v.get("revision")).intValue();}
    @Test void removedRegistrationRetainsFilesAndAuditButCannotBeUsedOrEnabled()throws Exception{
        var before=installed();String operation=(String)before.get("operationId");
        var directory=service.directory(alice.userId(),operation);Files.createDirectories(directory);var license=directory.resolve("LICENSE");Files.writeString(license,"PRIVATE_LICENSE_FIXTURE");
        var removed=service.removeRegistration(alice,revision(before),operation,true);
        assertThat(removed).containsEntry("status","UNINSTALLED").containsEntry("enabled",false).containsEntry("manifest",null).containsEntry("requiresMigration",false).containsEntry("registrationRemovalSupported",true);
        assertThat(Files.readString(license)).isEqualTo("PRIVATE_LICENSE_FIXTURE");assertThat(service.available(alice)).isFalse();
        assertThatThrownBy(()->service.enabled(alice,revision(removed),true)).hasMessageContaining("安装");
        assertThatThrownBy(()->service.probe(alice)).hasMessageContaining("本人");
        assertThat(service.fetch(alice,null,null,Map.of("url","https://1.1.1.1/")).block().getState().toString()).isEqualTo("ERROR");
        service.removeRegistration(alice,revision(before),operation,true);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_local_mcp_audit WHERE action_name='REMOVE_REGISTRATION'",Integer.class)).isEqualTo(1);
        assertThat(jdbc.queryForList("SELECT detail_json FROM agent_local_mcp_audit WHERE action_name='REMOVE_REGISTRATION'").toString()).contains("filesRetained","registrationRemoved").doesNotContain("PRIVATE_LICENSE_FIXTURE");
        assertThat(jdbc.queryForMap("SELECT manifest_sha256,lease_expires_at,error_code FROM agent_local_mcp WHERE owner_user_id=1").values()).containsOnlyNulls();
        verify(runtime,never()).open(any(),any());
    }
    @Test void enabledInstallationMustBeExplicitlyDisabledBeforeRemoval()throws Exception{
        var before=installed();var enabled=service.enabled(alice,revision(before),true);String operation=(String)enabled.get("operationId");
        assertThatThrownBy(()->service.removeRegistration(alice,revision(enabled),operation,true)).hasMessageContaining("先停用");assertThat(service.available(alice)).isTrue();
        var disabled=service.enabled(alice,revision(enabled),false);assertThat(service.removeRegistration(alice,revision(disabled),operation,true)).containsEntry("status","UNINSTALLED");
    }
    @Test void removalRequiresCurrentOwnerConsentRevisionAndFreshAccount()throws Exception{
        var before=installed();String operation=(String)before.get("operationId");
        assertThatThrownBy(()->service.removeRegistration(boss,0,operation,true)).hasMessageContaining("任务已变化");
        assertThatThrownBy(()->service.removeRegistration(alice,revision(before),operation,false)).hasMessageContaining("确认");
        assertThatThrownBy(()->service.removeRegistration(alice,revision(before),"../other",true)).hasMessageContaining("确认");
        assertThatThrownBy(()->service.removeRegistration(alice,0,operation,true)).hasMessageContaining("状态已变化");
        assertThat(service.view(alice)).containsEntry("status","INSTALLED");
        when(users.current(1,"alice")).thenThrow(new SecurityException("ACCOUNT_REVOKED"));
        assertThatThrownBy(()->service.removeRegistration(alice,revision(before),operation,true)).isInstanceOf(SecurityException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_local_mcp_audit WHERE action_name='REMOVE_REGISTRATION'",Integer.class)).isZero();
    }
    @Test void removalAuditFailureRollsBackManifestAndRevision()throws Exception{
        var before=installed();
        jdbc.execute("ALTER TABLE agent_local_mcp_audit ADD CONSTRAINT deny_remove CHECK(action_name<>'REMOVE_REGISTRATION')");
        assertThatThrownBy(()->service.removeRegistration(alice,revision(before),(String)before.get("operationId"),true)).isInstanceOf(org.springframework.dao.DataAccessException.class);
        var after=service.view(alice);assertThat(after).containsEntry("status","INSTALLED").containsEntry("revision",before.get("revision")).containsEntry("manifest",before.get("manifest"));
    }
    @Test void reinstallationAfterRemovalUsesANewOperationAndRejectsOldRemoval()throws Exception{
        var before=installed();String operation=(String)before.get("operationId");var removed=service.removeRegistration(alice,revision(before),operation,true);
        assertThatThrownBy(()->service.install(alice,revision(removed),"request-reinstall",false)).hasMessageContaining("许可证");
        service.install(alice,revision(removed),"request-reinstall",true);await().atMost(Duration.ofSeconds(3)).until(()->"INSTALLED".equals(service.view(alice).get("status")));
        var after=service.view(alice);assertThat(after.get("operationId")).isNotEqualTo(operation);assertThat(after).containsEntry("enabled",false);
        assertThatThrownBy(()->service.removeRegistration(alice,revision(before),operation,true)).hasMessageContaining("任务已变化");assertThat(service.view(alice)).containsEntry("status","INSTALLED");verify(runtime,times(2)).install(any());
    }
    @Test void removalDoesNotReplaceInstallationCancellation()throws Exception{
        var entered=new CountDownLatch(1);when(runtime.install(any())).thenAnswer(inv->{entered.countDown();new CountDownLatch(1).await();return Map.of();});
        service.install(alice,0,"request-remove-running",true);assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();var before=service.view(alice);String operation=(String)before.get("operationId");
        assertThatThrownBy(()->service.removeRegistration(alice,revision(before),operation,true)).hasMessageContaining("先取消");
        var cancelled=service.cancelInstallation(alice,revision(before),operation,true);
        assertThatThrownBy(()->service.removeRegistration(alice,revision(cancelled),operation,true)).hasMessageContaining("仅已完成");
        assertThat(service.view(alice)).containsEntry("status","CANCELLED");
    }
    @Test void disabledOutdatedOrTamperedManifestCanBeRemovedWithoutOpeningIt()throws Exception{
        var before=installed();when(runtime.requiresMigration(any())).thenReturn(true);
        assertThat(service.view(alice)).containsEntry("requiresMigration",true);
        jdbc.update("UPDATE agent_local_mcp SET manifest_sha256=? WHERE owner_user_id=1","0".repeat(64));clearInvocations(runtime);
        assertThat(service.removeRegistration(alice,revision(before),(String)before.get("operationId"),true)).containsEntry("status","UNINSTALLED").containsEntry("manifest",null);
        verify(runtime,never()).validate(any(),any());verify(runtime,never()).open(any(),any());
    }
    @Test void concurrentEnableAndRemovalAcrossServicesCannotBothSucceed()throws Exception{
        var before=installed();var properties=new AgentScopeProperties();properties.setWorkspace(root.toString());
        var other=new LocalMcpService(jdbc,new DataSourceTransactionManager(jdbc.getDataSource()),new ObjectMapper(),users,properties,runtime);
        var executor=Executors.newFixedThreadPool(2);var start=new CountDownLatch(1);
        try{
            Callable<Boolean> enable=()->{start.await();try{service.enabled(alice,revision(before),true);return true;}catch(org.springframework.web.server.ResponseStatusException e){assertThat(e.getStatusCode().value()).isEqualTo(409);return false;}};
            Callable<Boolean> remove=()->{start.await();try{other.removeRegistration(alice,revision(before),(String)before.get("operationId"),true);return true;}catch(org.springframework.web.server.ResponseStatusException e){assertThat(e.getStatusCode().value()).isEqualTo(409);return false;}};
            var enabled=executor.submit(enable);var removed=executor.submit(remove);start.countDown();
            assertThat(List.of(enabled.get(4,TimeUnit.SECONDS),removed.get(4,TimeUnit.SECONDS))).containsExactlyInAnyOrder(true,false);
            var after=service.view(alice);assertThat(after.get("status")).isIn("INSTALLED","UNINSTALLED");assertThat(after.get("enabled")).isEqualTo("INSTALLED".equals(after.get("status")));
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_local_mcp_audit WHERE action_name IN ('ENABLE','REMOVE_REGISTRATION')",Integer.class)).isEqualTo(1);
        }finally{start.countDown();executor.shutdownNow();other.close();}
    }
    @Test void runningInstallationCanBeCancelledAndReplaysOnlyAuditOnce()throws Exception{
        var entered=new CountDownLatch(1);var interrupted=new CountDownLatch(1);
        when(runtime.install(any())).thenAnswer(inv->{entered.countDown();try{new CountDownLatch(1).await();return Map.of();}catch(InterruptedException error){interrupted.countDown();throw error;}});
        service.install(alice,0,"request-cancel-one",true);assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();
        var before=service.view(alice);String operation=(String)before.get("operationId");
        var cancelled=service.cancelInstallation(alice,revision(before),operation,true);
        assertThat(cancelled).containsEntry("status","CANCELLED").containsEntry("enabled",false).containsEntry("operationId",operation);
        assertThat(interrupted.await(2,TimeUnit.SECONDS)).isTrue();service.cancelInstallation(alice,revision(before),operation,true);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_local_mcp_audit WHERE action_name='CANCEL_INSTALL'",Integer.class)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT lease_expires_at FROM agent_local_mcp WHERE owner_user_id=1",LocalDateTime.class)).isNull();
        assertThatThrownBy(()->service.enabled(alice,revision(cancelled),true)).hasMessageContaining("安装");
    }
    @Test void queuedCancellationSkipsRuntimeAndFreesQueueCapacity()throws Exception{
        var entered=new CountDownLatch(1);var release=new CountDownLatch(1);
        when(runtime.install(any())).thenAnswer(inv->{entered.countDown();release.await(3,TimeUnit.SECONDS);return Map.of("version",FetchMcpRuntime.VERSION);});
        service.install(alice,0,"request-running-one",true);assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();
        service.install(bob,0,"request-queued-one",true);var queued=service.view(bob);
        var executor=(ThreadPoolExecutor)org.springframework.test.util.ReflectionTestUtils.getField(service,"jobs");assertThat(executor.getQueue()).hasSize(1);
        service.cancelInstallation(bob,revision(queued),(String)queued.get("operationId"),true);assertThat(executor.getQueue()).isEmpty();release.countDown();
        await().atMost(Duration.ofSeconds(3)).until(()->"INSTALLED".equals(service.view(alice).get("status")));
        verify(runtime,times(1)).install(any());assertThat(service.view(bob)).containsEntry("status","CANCELLED");
    }
    @Test void cancelledRegistrationCannotBeOverwrittenByAnUncooperativeLateWorker()throws Exception{
        var entered=new CountDownLatch(1);var interrupted=new CountDownLatch(1);var release=new CountDownLatch(1);var returned=new CountDownLatch(1);
        when(runtime.install(any())).thenAnswer(inv->{entered.countDown();try{release.await();}catch(InterruptedException error){interrupted.countDown();release.await(3,TimeUnit.SECONDS);}returned.countDown();return Map.of("version",FetchMcpRuntime.VERSION);});
        try{
            service.install(alice,0,"request-late-one",true);assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();var before=service.view(alice);
            service.cancelInstallation(alice,revision(before),(String)before.get("operationId"),true);assertThat(interrupted.await(2,TimeUnit.SECONDS)).isTrue();release.countDown();assertThat(returned.await(2,TimeUnit.SECONDS)).isTrue();
            // 排队一个只读屏障，确保旧安装的数据库回写逻辑已经结束。
            var executor=(ThreadPoolExecutor)org.springframework.test.util.ReflectionTestUtils.getField(service,"jobs");executor.submit(()->{}).get(3,TimeUnit.SECONDS);
            assertThat(service.view(alice)).containsEntry("status","CANCELLED").containsEntry("enabled",false);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_local_mcp_audit WHERE action_name='INSTALL' AND outcome='SUCCEEDED'",Integer.class)).isZero();
        }finally{release.countDown();}
    }
    @Test void cancelledInstallMayBeReinstalledButAnOldCancelCannotAffectTheNewOperation()throws Exception{
        var first=new CountDownLatch(1);when(runtime.install(any())).thenAnswer(inv->{first.countDown();new CountDownLatch(1).await();return Map.of();});
        service.install(alice,0,"request-first-one",true);assertThat(first.await(2,TimeUnit.SECONDS)).isTrue();var before=service.view(alice);String old=(String)before.get("operationId");
        var cancelled=service.cancelInstallation(alice,revision(before),old,true);
        doReturn(Map.of("version",FetchMcpRuntime.VERSION)).when(runtime).install(any());service.install(alice,revision(cancelled),"request-second-one",true);
        await().atMost(Duration.ofSeconds(3)).until(()->"INSTALLED".equals(service.view(alice).get("status")));
        assertThatThrownBy(()->service.cancelInstallation(alice,revision(before),old,true)).hasMessageContaining("已变化");
        assertThat(service.view(alice)).containsEntry("status","INSTALLED").containsEntry("enabled",false);
    }
    @Test void cancelledInstallationNeverDeletesExistingFiles()throws Exception{
        var entered=new CountDownLatch(1);when(runtime.install(any())).thenAnswer(inv->{entered.countDown();new CountDownLatch(1).await();return Map.of();});
        service.install(alice,0,"request-files-one",true);assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();var before=service.view(alice);String operation=(String)before.get("operationId");
        var directory=service.directory(alice.userId(),operation);Files.createDirectories(directory);var file=directory.resolve("partial-download.bin");Files.writeString(file,"PRIVATE_PARTIAL_FILE");
        service.cancelInstallation(alice,revision(before),operation,true);assertThat(Files.readString(file)).isEqualTo("PRIVATE_PARTIAL_FILE");
        assertThat(jdbc.queryForList("SELECT detail_json FROM agent_local_mcp_audit WHERE action_name='CANCEL_INSTALL'").toString()).contains("filesRetained").doesNotContain("PRIVATE_PARTIAL_FILE");
    }
    @Test void ownerConfirmationRevisionAndCurrentOperationAreRequiredForCancellation()throws Exception{
        var entered=new CountDownLatch(1);when(runtime.install(any())).thenAnswer(inv->{entered.countDown();new CountDownLatch(1).await();return Map.of();});
        service.install(alice,0,"request-private-one",true);assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();var before=service.view(alice);String operation=(String)before.get("operationId");
        assertThatThrownBy(()->service.cancelInstallation(boss,0,operation,true)).hasMessageContaining("任务已变化");
        assertThatThrownBy(()->service.cancelInstallation(alice,revision(before),operation,false)).hasMessageContaining("确认");
        assertThatThrownBy(()->service.cancelInstallation(alice,0,operation,true)).hasMessageContaining("状态已变化");
        assertThat(service.view(alice)).containsEntry("status","INSTALLING");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_local_mcp_audit WHERE action_name='CANCEL_INSTALL'",Integer.class)).isZero();
    }
    @Test void cancelAuditFailureRollsBackAndDoesNotInterruptTheWorker()throws Exception{
        var entered=new CountDownLatch(1);var interrupted=new CountDownLatch(1);var release=new CountDownLatch(1);
        when(runtime.install(any())).thenAnswer(inv->{entered.countDown();try{release.await(3,TimeUnit.SECONDS);}catch(InterruptedException error){interrupted.countDown();throw error;}return Map.of("version",FetchMcpRuntime.VERSION);});
        service.install(alice,0,"request-audit-one",true);assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();var before=service.view(alice);
        jdbc.execute("ALTER TABLE agent_local_mcp_audit ADD CONSTRAINT deny_cancel CHECK(action_name<>'CANCEL_INSTALL')");
        assertThatThrownBy(()->service.cancelInstallation(alice,revision(before),(String)before.get("operationId"),true)).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(interrupted.getCount()).isEqualTo(1);assertThat(service.view(alice)).containsEntry("status","INSTALLING");release.countDown();
        await().atMost(Duration.ofSeconds(3)).until(()->"INSTALLED".equals(service.view(alice).get("status")));
    }
    @Test void completedInstallCannotBeCancelledOrDowngraded()throws Exception{
        var done=installed();assertThatThrownBy(()->service.cancelInstallation(alice,revision(done),(String)done.get("operationId"),true)).hasMessageContaining("已结束");
        assertThat(service.view(alice)).containsEntry("status","INSTALLED");
    }
    @Test void interruptedNativeInstallerDoesNotCreateFilesOrStartDownload()throws Exception{
        var properties=new LocalMcpProperties();properties.setTransport("STDIO");var nativeRuntime=new FetchMcpRuntime(properties,new ObjectMapper());var failure=new java.util.concurrent.atomic.AtomicReference<Throwable>();
        var target=root.resolve("not-created");var thread=new Thread(()->{Thread.currentThread().interrupt();try{nativeRuntime.install(target);}catch(Throwable error){failure.set(error);}});thread.start();thread.join(2000);
        assertThat(failure.get()).isInstanceOf(InterruptedException.class);assertThat(target).doesNotExist();
    }
    @Test void installsArePrivateDisabledAndRequestDeduplicatesWithoutAffectingOtherUsers()throws Exception{var view=installed();assertThat(view).containsEntry("enabled",false).containsEntry("directory","users/1/mcp/fetch");assertThat(service.view(boss)).containsEntry("status","NOT_INSTALLED");assertThat(service.view(bob)).containsEntry("status","NOT_INSTALLED");service.install(alice,0,"request-install-one",true);verify(runtime,times(1)).install(any());assertThat(service.available(alice)).isFalse();}
    @Test void consentRevisionAndLiveRunOwnershipAreRequired()throws Exception{assertThatThrownBy(()->service.install(alice,0,"request-install-one",false)).hasMessageContaining("许可证");verify(runtime,never()).install(any());verify(runtime,never()).open(any(),any());assertThatThrownBy(()->service.propose(alice,"foreign","call")).hasMessageContaining("运行");
        jdbc.update("INSERT INTO agent_run VALUES('own-run',1,'employee-main','RUNNING',?)",LocalDateTime.now().plusMinutes(2));var proposed=service.propose(alice,"own-run","call");assertThat(proposed).containsEntry("status","PENDING_CONFIRM");verify(runtime,never()).install(any());verify(runtime,never()).open(any(),any());assertThatThrownBy(()->service.install(alice,0,"new-request",true)).hasMessageContaining("已变化");}
    @Test void installationFailureCannotEnableAndKeepsAudit()throws Exception{when(runtime.install(any())).thenThrow(new IllegalStateException("INSTALL_FAILED"));service.install(alice,0,"request-install-one",true);await().atMost(Duration.ofSeconds(3)).until(()->"ERROR".equals(service.view(alice).get("status")));var view=service.view(alice);assertThat(view).containsEntry("enabled",false).containsEntry("errorCode","INSTALL_FAILED");assertThatThrownBy(()->service.enabled(alice,revision(view),true)).hasMessageContaining("安装");assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_local_mcp_audit WHERE outcome='FAILED'",Long.class)).isEqualTo(1);}
    @Test void changedRuntimeRequiresOwnerConsentAndMigrationStaysDisabled()throws Exception{var view=installed();when(runtime.upgradeAvailable(any())).thenReturn(true);when(runtime.requiresMigration(any())).thenReturn(true);assertThat(service.view(alice)).containsEntry("requiresMigration",true);assertThatThrownBy(()->service.install(alice,revision(view),"migration-request",false)).hasMessageContaining("许可证");verify(runtime,times(1)).install(any());service.install(alice,revision(view),"migration-request",true);await().atMost(Duration.ofSeconds(3)).untilAsserted(()->verify(runtime,times(2)).install(any()));await().atMost(Duration.ofSeconds(3)).until(()->"INSTALLED".equals(service.view(alice).get("status")));assertThat(service.view(alice)).containsEntry("enabled",false);assertThat(service.view(bob)).containsEntry("status","NOT_INSTALLED");}
    @Test void auditFailureRollsBackInstallationStateBeforeAnyCommandRuns()throws Exception{jdbc.execute("ALTER TABLE agent_local_mcp_audit ADD CONSTRAINT deny_install CHECK(action_name<>'INSTALL')");assertThatThrownBy(()->service.install(alice,0,"request-install-one",true)).isInstanceOf(org.springframework.dao.DataAccessException.class);verify(runtime,never()).install(any());verify(runtime,never()).open(any(),any());assertThat(service.view(alice)).containsEntry("status","NOT_INSTALLED");}
    @Test void enabledAndDisabledAreRecheckedAndSuccessfulCallClosesSessionWithoutSavingUrlOrBody()throws Exception{var view=installed();service.enabled(alice,revision(view),true);var args=Map.<String,Object>of("url","https://1.1.1.1/");assertThat(service.fetch(alice,null,null,args).block().getOutput().toString()).contains("public page fixture");var session=runtime.open(null,null);verify(session).close();
        var records=jdbc.queryForList("SELECT detail_json FROM agent_local_mcp_audit WHERE action_name='CALL'");assertThat(records.toString()).contains("urlSha256").doesNotContain("https://1.1.1.1","public page fixture");
        view=service.view(alice);service.enabled(alice,revision(view),false);clearInvocations(runtime);assertThat(service.fetch(alice,null,null,args).block().getState().toString()).isEqualTo("ERROR");verify(runtime,never()).open(any(),any());assertThatThrownBy(()->service.assertEnabled(bob,args)).hasMessageContaining("本人");}
    @Test void disableClosesActiveStdioCallsAndCancellationIsAudited()throws Exception{var view=installed();service.enabled(alice,revision(view),true);var session=mock(FetchMcpRuntime.Session.class);when(session.call(any())).thenReturn(Mono.never());when(runtime.open(any(),any())).thenReturn(session);
        var call=service.fetch(alice,null,null,Map.of("url","https://1.1.1.1/")).subscribe();await().atMost(Duration.ofSeconds(2)).untilAsserted(()->verify(session).call(any()));service.enabled(alice,revision(service.view(alice)),false);verify(session).close();call.dispose();await().atMost(Duration.ofSeconds(2)).until(()->jdbc.queryForObject("SELECT COUNT(*) FROM agent_local_mcp_audit WHERE outcome='CANCELLED'",Long.class)>0);}
    @Test void tamperedManifestCannotBeEnabled()throws Exception{var view=installed();jdbc.update("UPDATE agent_local_mcp SET manifest_json='{}'");assertThatThrownBy(()->service.enabled(alice,revision(view),true)).hasMessageContaining("完整性");assertThat(service.view(alice)).containsEntry("enabled",false);}
    @Test void leaseExpiryCannotBeCompletedByOldWorker()throws Exception{var entered=new CountDownLatch(1);var release=new CountDownLatch(1);when(runtime.install(any())).thenAnswer(inv->{entered.countDown();release.await(3,TimeUnit.SECONDS);return Map.of("version",FetchMcpRuntime.VERSION);});service.install(alice,0,"request-install-one",true);assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();jdbc.update("UPDATE agent_local_mcp SET lease_expires_at=?",LocalDateTime.now().minusMinutes(1));service.expire();release.countDown();assertThat(service.view(alice)).containsEntry("status","ERROR").containsEntry("errorCode","INSTALL_LEASE_EXPIRED");}
    @Test void addressesArgumentsAndPathTraversalAreRejected(){for(String url:List.of("http://127.0.0.1:8080/","http://localhost/","file:///etc/passwd","https://user:password@example.com/","http://10.0.0.1/","http://169.254.169.254/","http://100.64.0.1/","http://192.0.2.1/","https://example.com/?token=hidden"))assertThatThrownBy(()->FetchUrlPolicy.validate(url)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(()->service.directory(1,"../../user")).hasMessageContaining("路径");assertThatThrownBy(()->FetchMcpRuntime.safeFile(root,"../password")).hasMessageContaining("PATH");assertThatThrownBy(()->FetchMcpRuntime.safeFile(root,"C:/secret")).hasMessageContaining("PATH");}
    @Test void evidenceStorageFailureWithholdsUnrecordedTextClosesSessionsAndReleasesCapacity() throws Exception {
        var research=mock(com.ruanzhu.doorhandle.module.ai.research.ResearchEvidenceService.class);
        when(research.capture(any(),anyString(),anyString(),anyMap(),any())).thenThrow(new org.springframework.dao.DataAccessResourceFailureException("PRIVATE_DATABASE_ERROR"));
        var properties=new AgentScopeProperties();properties.setWorkspace(root.toString());service.close();
        service=new LocalMcpService(jdbc,new DataSourceTransactionManager(jdbc.getDataSource()),new ObjectMapper(),users,properties,runtime,research);
        var view=installed();service.enabled(alice,revision(view),true);
        jdbc.update("INSERT INTO agent_run VALUES('own-run',1,'employee-main','RUNNING',?)",LocalDateTime.now().plusMinutes(2));
        var session=mock(FetchMcpRuntime.Session.class);when(session.call(any())).thenReturn(Mono.just(ToolResultBlock.text("PRIVATE_UNRECORDED_TEXT")));when(runtime.open(any(),any())).thenReturn(session);
        for(int i=0;i<3;i++) {
            var result=service.fetch(alice,"own-run","fetch-"+i,Map.of("url","https://1.1.1.1/")).block(Duration.ofSeconds(3));
            assertThat(result.getState()).isEqualTo(io.agentscope.core.message.ToolResultState.ERROR);
            assertThat(result.getOutput().toString()).doesNotContain("PRIVATE_UNRECORDED_TEXT","PRIVATE_DATABASE_ERROR");
        }
        verify(session,times(3)).close();verify(research,times(3)).capture(any(),eq("own-run"),anyString(),anyMap(),any());
    }
    @Test void sourceQuotaFailureHasAnActionableSafeMessageAndStillClosesTheFetchSession() throws Exception {
        var research=mock(com.ruanzhu.doorhandle.module.ai.research.ResearchEvidenceService.class);
        when(research.capture(any(),anyString(),anyString(),anyMap(),any())).thenThrow(new com.ruanzhu.doorhandle.module.ai.research.ResearchEvidenceStorage.QuotaExceeded());
        var properties=new AgentScopeProperties();properties.setWorkspace(root.toString());service.close();
        service=new LocalMcpService(jdbc,new DataSourceTransactionManager(jdbc.getDataSource()),new ObjectMapper(),users,properties,runtime,research);
        var view=installed();service.enabled(alice,revision(view),true);
        jdbc.update("INSERT INTO agent_run VALUES('own-run',1,'employee-main','RUNNING',?)",LocalDateTime.now().plusMinutes(2));
        var session=mock(FetchMcpRuntime.Session.class);when(session.call(any())).thenReturn(Mono.just(ToolResultBlock.text("PRIVATE_UNRECORDED_TEXT")));when(runtime.open(any(),any())).thenReturn(session);
        var result=service.fetch(alice,"own-run","fetch-quota",Map.of("url","https://1.1.1.1/")).block(Duration.ofSeconds(3));
        assertThat(result.getState()).isEqualTo(io.agentscope.core.message.ToolResultState.ERROR);
        assertThat(result.getOutput().toString()).contains("额度已满").doesNotContain("PRIVATE_UNRECORDED_TEXT");verify(session).close();
    }
}
