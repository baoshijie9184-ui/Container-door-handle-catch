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

class LocalMcpServiceTest {
    @TempDir Path root;
    final AgentActor alice=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR),bob=new AgentActor(2,"bob",AgentActor.Role.INSPECTOR),boss=new AgentActor(3,"boss",AgentActor.Role.SUPERVISOR);
    JdbcTemplate jdbc;LocalMcpService service;FetchMcpRuntime runtime;BusinessUserDirectory users;
    @BeforeEach void setup()throws Exception{var source=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa","");jdbc=new JdbcTemplate(source);
        String ddl=Files.readString(Path.of("../sql/mysql/migration-V25-local-mcp.sql")).replace(" JSON "," TEXT ").replace(" ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin","").replaceAll("(?m)^\\s*(?:UNIQUE )?KEY .*\\n","").replaceAll(",\\s*\\)","\n)");for(String sql:ddl.split(";"))if(!sql.isBlank())jdbc.execute(sql);
        jdbc.execute("CREATE TABLE agent_run(run_id VARCHAR(128),user_id BIGINT,main_agent VARCHAR(64),status VARCHAR(16),lease_expires_at DATETIME)");
        users=mock(BusinessUserDirectory.class);for(var actor:List.of(alice,bob,boss))when(users.current(actor.userId(),actor.username())).thenReturn(new BusinessUserDirectory.Identity(actor.userId(),actor.username(),actor.supervisor()));
        runtime=mock(FetchMcpRuntime.class);when(runtime.install(any())).thenReturn(Map.of("serverKey","fetch","version",FetchMcpRuntime.VERSION,"packageSha256",FetchMcpRuntime.SHA));
        var session=mock(FetchMcpRuntime.Session.class);when(session.call(any())).thenReturn(Mono.just(ToolResultBlock.text("public page fixture")));when(runtime.open(any(),any())).thenReturn(session);
        var properties=new AgentScopeProperties();properties.setWorkspace(root.toString());service=new LocalMcpService(jdbc,new DataSourceTransactionManager(source),new ObjectMapper(),users,properties,runtime);service.schema();}
    @AfterEach void stop(){service.close();}
    Map<String,Object> installed()throws Exception{service.install(alice,0,"request-install-one",true);await().atMost(Duration.ofSeconds(3)).until(()->"INSTALLED".equals(service.view(alice).get("status")));return service.view(alice);}
    int revision(Map<String,Object> v){return ((Number)v.get("revision")).intValue();}
    @Test void installsArePrivateDisabledAndRequestDeduplicatesWithoutAffectingOtherUsers()throws Exception{var view=installed();assertThat(view).containsEntry("enabled",false).containsEntry("directory","users/1/mcp/fetch");assertThat(service.view(boss)).containsEntry("status","NOT_INSTALLED");assertThat(service.view(bob)).containsEntry("status","NOT_INSTALLED");service.install(alice,0,"request-install-one",true);verify(runtime,times(1)).install(any());assertThat(service.available(alice)).isFalse();}
    @Test void consentRevisionAndLiveRunOwnershipAreRequired()throws Exception{assertThatThrownBy(()->service.install(alice,0,"request-install-one",false)).hasMessageContaining("许可证");verifyNoInteractions(runtime);assertThatThrownBy(()->service.propose(alice,"foreign","call")).hasMessageContaining("运行");
        jdbc.update("INSERT INTO agent_run VALUES('own-run',1,'employee-main','RUNNING',?)",LocalDateTime.now().plusMinutes(2));var proposed=service.propose(alice,"own-run","call");assertThat(proposed).containsEntry("status","PENDING_CONFIRM");verify(runtime,never()).install(any());verify(runtime,never()).open(any(),any());assertThatThrownBy(()->service.install(alice,0,"new-request",true)).hasMessageContaining("已变化");}
    @Test void installationFailureCannotEnableAndKeepsAudit()throws Exception{when(runtime.install(any())).thenThrow(new IllegalStateException("INSTALL_FAILED"));service.install(alice,0,"request-install-one",true);await().atMost(Duration.ofSeconds(3)).until(()->"ERROR".equals(service.view(alice).get("status")));var view=service.view(alice);assertThat(view).containsEntry("enabled",false).containsEntry("errorCode","INSTALL_FAILED");assertThatThrownBy(()->service.enabled(alice,revision(view),true)).hasMessageContaining("安装");assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_local_mcp_audit WHERE outcome='FAILED'",Long.class)).isEqualTo(1);}
    @Test void auditFailureRollsBackInstallationStateBeforeAnyCommandRuns()throws Exception{jdbc.execute("ALTER TABLE agent_local_mcp_audit ADD CONSTRAINT deny_install CHECK(action_name<>'INSTALL')");assertThatThrownBy(()->service.install(alice,0,"request-install-one",true)).isInstanceOf(org.springframework.dao.DataAccessException.class);verifyNoInteractions(runtime);assertThat(service.view(alice)).containsEntry("status","NOT_INSTALLED");}
    @Test void enabledAndDisabledAreRecheckedAndSuccessfulCallClosesSessionWithoutSavingUrlOrBody()throws Exception{var view=installed();service.enabled(alice,revision(view),true);var args=Map.<String,Object>of("url","https://1.1.1.1/");assertThat(service.fetch(alice,null,null,args).block().getOutput().toString()).contains("public page fixture");var session=runtime.open(null,null);verify(session).close();
        var records=jdbc.queryForList("SELECT detail_json FROM agent_local_mcp_audit WHERE action_name='CALL'");assertThat(records.toString()).contains("urlSha256").doesNotContain("https://1.1.1.1","public page fixture");
        view=service.view(alice);service.enabled(alice,revision(view),false);clearInvocations(runtime);assertThat(service.fetch(alice,null,null,args).block().getState().toString()).isEqualTo("ERROR");verify(runtime,never()).open(any(),any());assertThatThrownBy(()->service.assertEnabled(bob,args)).hasMessageContaining("本人");}
    @Test void disableClosesActiveStdioCallsAndCancellationIsAudited()throws Exception{var view=installed();service.enabled(alice,revision(view),true);var session=mock(FetchMcpRuntime.Session.class);when(session.call(any())).thenReturn(Mono.never());when(runtime.open(any(),any())).thenReturn(session);
        var call=service.fetch(alice,null,null,Map.of("url","https://1.1.1.1/")).subscribe();await().atMost(Duration.ofSeconds(2)).untilAsserted(()->verify(session).call(any()));service.enabled(alice,revision(service.view(alice)),false);verify(session).close();call.dispose();await().atMost(Duration.ofSeconds(2)).until(()->jdbc.queryForObject("SELECT COUNT(*) FROM agent_local_mcp_audit WHERE outcome='CANCELLED'",Long.class)>0);}
    @Test void tamperedManifestCannotBeEnabled()throws Exception{var view=installed();jdbc.update("UPDATE agent_local_mcp SET manifest_json='{}'");assertThatThrownBy(()->service.enabled(alice,revision(view),true)).hasMessageContaining("完整性");assertThat(service.view(alice)).containsEntry("enabled",false);}
    @Test void leaseExpiryCannotBeCompletedByOldWorker()throws Exception{var entered=new CountDownLatch(1);var release=new CountDownLatch(1);when(runtime.install(any())).thenAnswer(inv->{entered.countDown();release.await(3,TimeUnit.SECONDS);return Map.of("version",FetchMcpRuntime.VERSION);});service.install(alice,0,"request-install-one",true);assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();jdbc.update("UPDATE agent_local_mcp SET lease_expires_at=?",LocalDateTime.now().minusMinutes(1));service.expire();release.countDown();assertThat(service.view(alice)).containsEntry("status","ERROR").containsEntry("errorCode","INSTALL_LEASE_EXPIRED");}
    @Test void addressesArgumentsAndPathTraversalAreRejected(){for(String url:List.of("http://127.0.0.1:8080/","http://localhost/","file:///etc/passwd","https://user:password@example.com/","http://10.0.0.1/","http://169.254.169.254/","http://100.64.0.1/","http://192.0.2.1/","https://example.com/?token=hidden"))assertThatThrownBy(()->FetchUrlPolicy.validate(url)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(()->service.directory(1,"../../user")).hasMessageContaining("路径");assertThatThrownBy(()->FetchMcpRuntime.safeFile(root,"../password")).hasMessageContaining("PATH");assertThatThrownBy(()->FetchMcpRuntime.safeFile(root,"C:/secret")).hasMessageContaining("PATH");}
}
