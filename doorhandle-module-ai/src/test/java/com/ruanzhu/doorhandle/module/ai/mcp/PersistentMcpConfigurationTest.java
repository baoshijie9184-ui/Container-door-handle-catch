package com.ruanzhu.doorhandle.module.ai.mcp;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.testsupport.CompactMcpFixture;
import com.ruanzhu.doorhandle.module.ai.testsupport.CompactWorkflowFixture;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import java.nio.file.*;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class PersistentMcpConfigurationTest {
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
    private String seedInstalledRegistration(JdbcTemplate jdbc,ObjectMapper mapper,long owner)throws Exception{
        String operation=UUID.randomUUID().toString();
        String manifest=mapper.copy().enable(com.fasterxml.jackson.databind.SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS)
            .writeValueAsString(Map.of("version",FetchMcpRuntime.VERSION,"privateMarker","PRIVATE_MANIFEST_TOKEN"));
        jdbc.update("INSERT INTO agent_connector(owner_user_id,server_key,package_version,status,enabled,revision,operation_id,manifest_json,manifest_sha256,created_at,updated_at) VALUES(?,'fetch',?,'INSTALLED',TRUE,4,?,?,?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",
            owner,FetchMcpRuntime.VERSION,operation,manifest,FetchMcpRuntime.sha(manifest.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
        return operation;
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
        runner(true).withUserConfiguration(Scheduling.class).withPropertyValues("agentscope.mcp.durable-install-enabled=true").run(ctx->{
            var entered=new java.util.concurrent.CountDownLatch(1);var interrupted=new java.util.concurrent.CountDownLatch(1);
            var runtime=ctx.getBean("fakeRuntime",FetchMcpRuntime.class);
            doAnswer(inv->{entered.countDown();try{new java.util.concurrent.CountDownLatch(1).await(10,java.util.concurrent.TimeUnit.SECONDS);}catch(InterruptedException error){interrupted.countDown();throw error;}return Map.of();}).when(runtime).install(any());
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
