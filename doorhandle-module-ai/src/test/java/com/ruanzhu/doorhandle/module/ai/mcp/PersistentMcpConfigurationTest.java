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
