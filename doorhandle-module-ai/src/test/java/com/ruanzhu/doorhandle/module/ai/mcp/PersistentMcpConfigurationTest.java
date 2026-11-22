package com.ruanzhu.doorhandle.module.ai.mcp;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import com.ruanzhu.doorhandle.module.ai.testsupport.CompactAgentJournalFixture;
import com.ruanzhu.doorhandle.module.ai.testsupport.CompactMcpFixture;
import com.ruanzhu.doorhandle.module.ai.testsupport.CompactWorkflowFixture;
import io.agentscope.core.message.ToolResultBlock;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;
import java.time.Duration;
import java.nio.file.*;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class PersistentMcpConfigurationTest {
    @org.springframework.context.annotation.Configuration(proxyBeanMethods=false)
    @org.springframework.scheduling.annotation.EnableScheduling
    static class SchedulerOnly {}

    @org.springframework.context.annotation.Configuration(proxyBeanMethods=false)
    @org.springframework.scheduling.annotation.EnableScheduling
    static class Scheduling {
        @org.springframework.context.annotation.Bean @org.springframework.context.annotation.Primary
        FetchMcpRuntime fakeRuntime()throws Exception{var runtime=mock(FetchMcpRuntime.class);when(runtime.writesAllowed()).thenReturn(true);when(runtime.installationIdentity()).thenReturn("a".repeat(64));when(runtime.install(any())).thenReturn(Map.of("version",FetchMcpRuntime.VERSION));return runtime;}
    }
    ApplicationContextRunner runner(boolean queueSchema)throws Exception{return runner(queueSchema,true);}
    ApplicationContextRunner runner(boolean queueSchema,boolean connectorSchema)throws Exception{
        var source=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa","");var jdbc=new JdbcTemplate(source);
        CompactWorkflowFixture.install(jdbc);
        // This class verifies Spring wiring and real scheduler admission. The
        // separate admitted MySQL suite verifies all production engine/trigger contracts.
        if(connectorSchema)CompactMcpFixture.installConnector(jdbc);
        if(!queueSchema)jdbc.execute("DROP TABLE workflow_instance");
        var users=mock(BusinessUserDirectory.class);when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",false));
        return new ApplicationContextRunner().withUserConfiguration(LocalMcpConfiguration.class)
            .withBean(JdbcTemplate.class,()->jdbc).withBean(org.springframework.transaction.PlatformTransactionManager.class,()->new DataSourceTransactionManager(source))
            .withBean(ObjectMapper.class,ObjectMapper::new).withBean(BusinessUserDirectory.class,()->users).withPropertyValues("agentscope.mcp.enabled=true");
    }
    @Test void compactConnectorFixturePreservesTheExistingAuditAndProductionChecks()throws Exception{
        var source=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa","");
        var jdbc=new JdbcTemplate(source);CompactWorkflowFixture.install(jdbc);
        var constraints=jdbc.queryForList("SELECT constraint_name FROM information_schema.table_constraints WHERE table_name='audit_event' ORDER BY constraint_name");
        CompactMcpFixture.installConnector(jdbc);
        assertThat(jdbc.queryForList("SELECT constraint_name FROM information_schema.table_constraints WHERE table_name='audit_event' ORDER BY constraint_name")).isEqualTo(constraints);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event",Long.class)).isZero();
        assertThat(jdbc.queryForList("SELECT id,legacy_clock_json,current_installation_id FROM agent_connector WHERE 1=0")).isEmpty();
        assertThatThrownBy(()->jdbc.update("INSERT INTO agent_connector(owner_user_id,server_key,package_version,revision,created_at,updated_at) VALUES(1,'fetch','fixture',-1,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))"))
            .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThatThrownBy(()->jdbc.update("INSERT INTO agent_connector(owner_user_id,server_key,package_version,created_at,updated_at) VALUES(1,'fetch','fixture',NULL,NULL)"))
            .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThatThrownBy(()->CompactMcpFixture.installConnector(jdbc)).isInstanceOf(org.springframework.jdbc.datasource.init.ScriptStatementFailedException.class);
    }
    @Test void mcpRunLeaseUsesUtcWithNonUtcDatabaseSession()throws Exception{
        var source=new DriverManagerDataSource(
            "jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1;INIT=SET TIME ZONE '+08:00'","sa","");
        var jdbc=new JdbcTemplate(source);
        CompactAgentJournalFixture.install(jdbc);
        CompactMcpFixture.installConnector(jdbc);
        jdbc.update("""
            INSERT INTO agent_run(run_id,user_id,session_id,main_agent,entry_point,request_key,status,
                default_model,policy_version,instance_id,started_at,heartbeat_at,lease_expires_at)
            VALUES('own-run',1,'mcp-fixture','employee-main','CHAT','own-run','RUNNING',
                'fixture','fixture','fixture',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6),DATEADD('MINUTE',2,UTC_TIMESTAMP(6)))
            """);
        var users=mock(BusinessUserDirectory.class);
        when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",false));
        when(users.current(2,"bob")).thenReturn(new BusinessUserDirectory.Identity(2,"bob",false));
        var runtime=mock(FetchMcpRuntime.class);
        when(runtime.writesAllowed()).thenReturn(true);
        var service=new LocalMcpService(jdbc,new DataSourceTransactionManager(source),new ObjectMapper(),users,new AgentScopeProperties(),runtime);
        var alice=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);
        var bob=new AgentActor(2,"bob",AgentActor.Role.INSPECTOR);
        try{
            assertThatThrownBy(()->service.propose(bob,"own-run","call")).hasMessageContaining("403");
            assertThat(service.propose(alice,"own-run","call")).containsEntry("status","PENDING_CONFIRM");
            jdbc.update("UPDATE agent_run SET lease_expires_at=DATEADD('SECOND',-1,UTC_TIMESTAMP(6)) WHERE run_id='own-run'");
            assertThatThrownBy(()->service.propose(alice,"own-run","call")).hasMessageContaining("403");
        }finally{service.close();}
    }
    private String seedInstalledRegistration(JdbcTemplate jdbc,ObjectMapper mapper,long owner)throws Exception{
        String operation=UUID.randomUUID().toString();
        String manifest=mapper.copy().enable(com.fasterxml.jackson.databind.SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS)
            .writeValueAsString(Map.of("version",FetchMcpRuntime.VERSION,"privateMarker","PRIVATE_MANIFEST_TOKEN"));
        jdbc.update("INSERT INTO agent_connector(owner_user_id,server_key,package_version,status,enabled,revision,operation_id,manifest_json,manifest_sha256,created_at,updated_at) VALUES(?,'fetch',?,'INSTALLED',TRUE,4,?,?,?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",
            owner,FetchMcpRuntime.VERSION,operation,manifest,FetchMcpRuntime.sha(manifest.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
        return operation;
    }
    @Test void toolResultAndReceiptSurviveClosingOutsideTheTransportThread()throws Exception{
        runner(false).withUserConfiguration(Scheduling.class).run(ctx->{
            assertThat(ctx).hasNotFailed();
            var jdbc=ctx.getBean(JdbcTemplate.class);
            seedInstalledRegistration(jdbc,ctx.getBean(ObjectMapper.class),1);
            var inbound=Schedulers.newSingle("mcp-inbound");
            var runtime=ctx.getBean("fakeRuntime",FetchMcpRuntime.class);
            var session=mock(FetchMcpRuntime.Session.class);
            when(runtime.open(any(),any())).thenReturn(session);
            when(session.call(any())).thenReturn(Mono.just(ToolResultBlock.text("public page")).publishOn(inbound));
            when(session.exitEvidence()).thenReturn(Map.of("exitVerified",true,"cleanupConfirmed",true));
            doAnswer(invocation->{
                assertThat(Schedulers.isInNonBlockingThread()).isFalse();
                return null;
            }).when(session).close();
            try{
                var actor=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);
                var result=ctx.getBean(LocalMcpService.class).fetch(actor,null,null,Map.of("url","https://1.1.1.1/"))
                    .block(Duration.ofSeconds(5));
                assertThat(result.getOutput().toString()).contains("public page");
                verify(session).close();
                assertThat(jdbc.queryForList("SELECT outcome FROM audit_event WHERE action='EXECUTION_EXIT'",String.class))
                    .containsExactly("REMOVED");
            }finally{inbound.dispose();}
        });
    }
    @Test void actualServiceAuditKeepsTypedPayloadOwnerRevisionAndPrivateDetails()throws Exception{
        runner(false).withUserConfiguration(Scheduling.class).run(ctx->{
            assertThat(ctx).hasNotFailed();
            var jdbc=ctx.getBean(JdbcTemplate.class);var mapper=ctx.getBean(ObjectMapper.class);
            String operation=seedInstalledRegistration(jdbc,mapper,1);seedInstalledRegistration(jdbc,mapper,2);
            var service=ctx.getBean(LocalMcpService.class);var actor=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);
            assertThat(service.enabled(actor,4,false)).containsEntry("enabled",false).containsEntry("revision",5);
            var rows=jdbc.queryForList("SELECT event_id,owner_user_id,resource_id,action,outcome,revision,request_id,run_id,call_id,occurred_at,kind,resource_type,payload_version,payload_json FROM audit_event");
            assertThat(rows).hasSize(1);var row=rows.get(0);
            assertThat(UUID.fromString(row.get("event_id").toString())).isNotNull();
            assertThat(((Number)row.get("owner_user_id")).longValue()).isEqualTo(1);
            assertThat(row).containsEntry("resource_id","fetch").containsEntry("action","DISABLE").containsEntry("outcome","SUCCEEDED")
                .containsEntry("request_id",operation).containsEntry("run_id",null).containsEntry("call_id",null)
                .containsEntry("kind","MCP").containsEntry("resource_type","MCP_CONNECTOR");
            assertThat(((Number)row.get("revision")).intValue()).isEqualTo(5);
            assertThat(((Number)row.get("payload_version")).intValue()).isEqualTo(1);
            assertThat(row.get("occurred_at")).isNotNull();
            var payload=mapper.readTree(row.get("payload_json").toString());
            assertThat(payload.size()).isEqualTo(2);assertThat(payload.get("schemaVersion").isIntegralNumber()).isTrue();
            assertThat(payload.get("schemaVersion").intValue()).isEqualTo(1);assertThat(payload.get("detailJson").isTextual()).isTrue();
            assertThat(mapper.readTree(payload.get("detailJson").textValue())).isEqualTo(mapper.valueToTree(Map.of("version",FetchMcpRuntime.VERSION)));
            assertThat(rows.toString()).doesNotContain("PRIVATE_MANIFEST_TOKEN","privateMarker");
            assertThat(jdbc.queryForObject("SELECT enabled FROM agent_connector WHERE owner_user_id=2",Boolean.class)).isTrue();
            assertThat(jdbc.queryForObject("SELECT revision FROM agent_connector WHERE owner_user_id=2",Integer.class)).isEqualTo(4);
            assertThatThrownBy(()->service.enabled(actor,4,false)).hasMessageContaining("409");
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event",Long.class)).isEqualTo(1);
        });
    }
    @Test void actualAuditConstraintFailureRollsBackTheRegistrationAndNeverStartsACommand()throws Exception{
        runner(false).withUserConfiguration(Scheduling.class).run(ctx->{
            assertThat(ctx).hasNotFailed();
            var jdbc=ctx.getBean(JdbcTemplate.class);seedInstalledRegistration(jdbc,ctx.getBean(ObjectMapper.class),1);
            var before=jdbc.queryForMap("SELECT * FROM agent_connector WHERE owner_user_id=1");
            jdbc.execute("ALTER TABLE audit_event ADD CONSTRAINT deny_fixture_disable CHECK(kind<>'MCP' OR action<>'DISABLE')");
            var actor=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);var service=ctx.getBean(LocalMcpService.class);
            assertThatThrownBy(()->service.enabled(actor,4,false)).isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
            assertThat(jdbc.queryForMap("SELECT * FROM agent_connector WHERE owner_user_id=1")).isEqualTo(before);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event",Long.class)).isZero();
            var runtime=ctx.getBean("fakeRuntime",FetchMcpRuntime.class);
            verify(runtime,never()).install(any());verify(runtime,never()).open(any(),any());
        });
    }
    @Test void defaultMemoryModeDoesNotRequireQueueMigration()throws Exception{
        runner(false).run(ctx->{assertThat(ctx).hasNotFailed();assertThat(ctx.getBean(LocalMcpProperties.class).isDurableInstallEnabled()).isFalse();assertThat(ctx.getBean(LocalMcpService.class).view(new AgentActor(1,"alice",AgentActor.Role.INSPECTOR))).containsEntry("installQueue","MEMORY");});
    }
    @Test void enablingDurableModeRequiresSchemaAndBindsSpringProperty()throws Exception{
        runner(false).withPropertyValues("agentscope.mcp.durable-install-enabled=true").run(ctx->{assertThat(ctx).hasFailed();assertThat(ctx.getStartupFailure()).hasStackTraceContaining("workflow_instance");});
        runner(true).withPropertyValues("agentscope.mcp.durable-install-enabled=true").run(ctx->{assertThat(ctx).hasNotFailed();assertThat(ctx.getBean(LocalMcpService.class).view(new AgentActor(1,"alice",AgentActor.Role.INSPECTOR))).containsEntry("installQueue","DURABLE");});
    }
    @Test void compactRegistrationSchemaIsRequiredEvenWhenDurableQueueIsDisabled()throws Exception{
        runner(false,false).run(ctx->{assertThat(ctx).hasFailed();assertThat(ctx.getStartupFailure()).hasStackTraceContaining("agent_connector");});
    }
    @Test void migrationCopiesAreIdentical()throws Exception{
        assertThat(Files.readAllBytes(Path.of("../sql/mysql/migration-V34-mcp-install-queue.sql"))).isEqualTo(Files.readAllBytes(Path.of("src/main/resources/db/migration-V34-mcp-install-queue.sql")));
    }
    @Test void dedicatedSpringSchedulerActuallyDispatchesPersistedTask()throws Exception{
        runner(true).withUserConfiguration(Scheduling.class).withPropertyValues("agentscope.mcp.durable-install-enabled=true").run(ctx->{
            assertThat(ctx).hasNotFailed();var service=ctx.getBean(LocalMcpService.class);var actor=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);
            service.install(actor,0,"request-real-scheduler",true);
            org.awaitility.Awaitility.await().atMost(java.time.Duration.ofSeconds(4)).until(()->"INSTALLED".equals(service.view(actor).get("status")));
            verify(ctx.getBean("fakeRuntime",FetchMcpRuntime.class),times(1)).install(any());
            String operation=(String)service.view(actor).get("operationId");
            var job=ctx.getBean(JdbcTemplate.class).queryForMap("SELECT resource_id,owner_user_id,mcp_owner_username,mcp_runtime_sha256,request_id,request_sha256,status,payload_version,payload_json FROM workflow_instance WHERE kind='MCP_INSTALL_JOB' AND resource_id=?",operation);
            assertThat(job).containsEntry("resource_id",operation).containsEntry("request_id",operation)
                .containsEntry("mcp_owner_username","alice").containsEntry("mcp_runtime_sha256","a".repeat(64)).containsEntry("status","SUCCEEDED");
            assertThat(((Number)job.get("owner_user_id")).longValue()).isEqualTo(actor.userId());
            assertThat(job.get("request_sha256")).isEqualTo(FetchMcpRuntime.sha(operation.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
            assertThat(((Number)job.get("payload_version")).intValue()).isEqualTo(1);
            assertThat(ctx.getBean(ObjectMapper.class).readTree(job.get("payload_json").toString()))
                .isEqualTo(ctx.getBean(ObjectMapper.class).readTree("{\"schemaVersion\":1}"));
        });
    }
    @Test void realSpringSchedulerObservesRemoteCancelWhileTheInstallerIsBusy()throws Exception{
        var entered=new java.util.concurrent.CountDownLatch(1);var interrupted=new java.util.concurrent.CountDownLatch(1);
        var runtime=mock(FetchMcpRuntime.class);
        when(runtime.writesAllowed()).thenReturn(true);when(runtime.installationIdentity()).thenReturn("a".repeat(64));
        doAnswer(inv->{entered.countDown();try{new java.util.concurrent.CountDownLatch(1).await(10,java.util.concurrent.TimeUnit.SECONDS);}catch(InterruptedException error){interrupted.countDown();throw error;}return Map.of();}).when(runtime).install(any());
        // Finish every stub before Spring publishes this mock to scheduler threads.
        runner(true).withUserConfiguration(SchedulerOnly.class)
            .withBean("fakeRuntime",FetchMcpRuntime.class,()->runtime,definition->definition.setPrimary(true))
            .withPropertyValues("agentscope.mcp.durable-install-enabled=true").run(ctx->{
            assertThat(ctx).hasNotFailed();assertThat(ctx.getBean("fakeRuntime",FetchMcpRuntime.class)).isSameAs(runtime);
            var service=ctx.getBean(LocalMcpService.class);var actor=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);
            service.install(actor,0,"request-scheduled-cancel",true);assertThat(entered.await(4,java.util.concurrent.TimeUnit.SECONDS)).isTrue();
            var jdbc=ctx.getBean(JdbcTemplate.class);
            var other=new LocalMcpService(jdbc,ctx.getBean(org.springframework.transaction.PlatformTransactionManager.class),ctx.getBean(ObjectMapper.class),
                    ctx.getBean(BusinessUserDirectory.class),ctx.getBean(com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties.class),runtime,null,new PersistentMcpInstallQueue(jdbc));
            try{
                other.schema();var running=other.view(actor);other.cancelInstallation(actor,((Number)running.get("revision")).intValue(),(String)running.get("operationId"),true);
                assertThat(interrupted.await(4,java.util.concurrent.TimeUnit.SECONDS)).isTrue();assertThat(service.view(actor)).containsEntry("status","CANCELLED");
            }finally{other.close();}
        });
    }
}
