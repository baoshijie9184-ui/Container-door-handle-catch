package com.ruanzhu.doorhandle.module.ai.research;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.ai.journal.AgentJournal;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** 验证真实 Spring 条件装配，已有 V31 部署无需因关闭的治理功能升级数据库。 */
class ResearchEvidenceConfigurationTest {
    final JdbcTemplate jdbc=mock(JdbcTemplate.class);
    final AgentJournal journal=mock(AgentJournal.class);
    ApplicationContextRunner context(){
        when(journal.enabled()).thenReturn(true);
        return new ApplicationContextRunner()
                .withUserConfiguration(ResearchEvidenceService.class,ResearchEvidenceStorage.class,ResearchEvidenceExportService.class,ResearchExportRateLimit.class)
                .withBean(JdbcTemplate.class,()->jdbc)
                .withBean(PlatformTransactionManager.class,()->mock(PlatformTransactionManager.class))
                .withBean(AgentJournal.class,()->journal)
                .withBean(ObjectMapper.class,ObjectMapper::new);
    }
    @Test void defaultsLeaveEvidenceAndGovernanceDisabled(){
        context().run(ctx->{
            assertThat(ctx).hasNotFailed().doesNotHaveBean(ResearchEvidenceService.class).doesNotHaveBean(ResearchEvidenceStorage.class).doesNotHaveBean(ResearchEvidenceExportService.class);
            verify(jdbc,never()).queryForList(anyString());
        });
    }
    @Test void governanceFlagAloneCannotStartMaintenance(){
        context().withPropertyValues("agentscope.research.governance-enabled=true","agentscope.research.purge-enabled=true").run(ctx->{
            assertThat(ctx).hasNotFailed().doesNotHaveBean(ResearchEvidenceService.class).doesNotHaveBean(ResearchEvidenceStorage.class);
            verify(jdbc,never()).queryForList(anyString());
        });
    }
    @Test void existingEvidenceCanStartWithoutGovernanceTables(){
        context().withPropertyValues("agentscope.research.enabled=true").run(ctx->{
            assertThat(ctx).hasNotFailed().hasSingleBean(ResearchEvidenceService.class).doesNotHaveBean(ResearchEvidenceStorage.class);
            verify(jdbc,never()).queryForList(contains("agent_research_storage_owner"));
            assertThat(ctx).doesNotHaveBean(ResearchEvidenceExportService.class);
            verify(jdbc,never()).queryForList(contains("agent_research_export_audit"));
        });
    }
    @Test void exportRequiresEvidenceButCanRunIndependentlyOfStorageGovernance(){
        context().withPropertyValues("agentscope.research.export-enabled=true").run(ctx->assertThat(ctx).hasNotFailed().doesNotHaveBean(ResearchEvidenceExportService.class));
        context().withPropertyValues("agentscope.research.enabled=true","agentscope.research.export-enabled=true").run(ctx->{
            assertThat(ctx).hasNotFailed().hasSingleBean(ResearchEvidenceExportService.class).doesNotHaveBean(ResearchEvidenceStorage.class);
            verify(jdbc).queryForList(contains("agent_research_export_audit"));
        });
    }
    @Test void bothSwitchesEnableGovernanceButNeverPurgeByDefault(){
        context().withPropertyValues("agentscope.research.enabled=true","agentscope.research.governance-enabled=true").run(ctx->{
            assertThat(ctx).hasNotFailed().hasSingleBean(ResearchEvidenceStorage.class).hasSingleBean(ResearchEvidenceService.class);
            assertThat(ctx.getBean(ResearchEvidenceProperties.class).isPurgeEnabled()).isFalse();
            assertThat(ctx.getBean(ResearchEvidenceStorage.class).purgeExpiredBatch()).isZero();
            verify(jdbc).queryForList(contains("agent_research_storage_owner"));
            verify(jdbc).queryForList(contains("agent_research_content_purge"));
        });
    }
    @Test void optingIntoGovernanceRequiresMigrationBeforeStartup(){
        when(jdbc.queryForList(contains("agent_research_storage_owner"))).thenThrow(new DataAccessResourceFailureException("missing table"));
        context().withPropertyValues("agentscope.research.enabled=true","agentscope.research.governance-enabled=true").run(ctx->{
            assertThat(ctx).hasFailed();
            assertThat(ctx.getStartupFailure()).hasRootCauseMessage("请先执行 migration-V32-agent-research-storage.sql 再启用存储治理");
        });
    }
    @Test void existingExportDoesNotReadTheOptionalLimitTable(){
        context().withPropertyValues("agentscope.research.enabled=true","agentscope.research.export-enabled=true").run(ctx->{
            assertThat(ctx).hasNotFailed().doesNotHaveBean(ResearchExportRateLimit.class);
            verify(jdbc,never()).queryForList(contains("agent_research_export_limit"));
        });
    }
    @Test void rateLimitFlagAloneOrWithoutExportCannotActivateTheLimit(){
        context().withPropertyValues("agentscope.research.export-rate-limit-enabled=true").run(ctx->assertThat(ctx).hasNotFailed().doesNotHaveBean(ResearchExportRateLimit.class));
        context().withPropertyValues("agentscope.research.enabled=true","agentscope.research.export-rate-limit-enabled=true").run(ctx->assertThat(ctx).hasNotFailed().doesNotHaveBean(ResearchExportRateLimit.class));
        verify(jdbc,never()).queryForList(contains("agent_research_export_limit"));
    }
    @Test void allThreeSwitchesWireTheLimitWithBoundProperties(){
        context().withPropertyValues("agentscope.research.enabled=true","agentscope.research.export-enabled=true","agentscope.research.export-rate-limit-enabled=true",
                "agentscope.research.export-max-per-window=3","agentscope.research.export-window-seconds=90").run(ctx->{
            assertThat(ctx).hasNotFailed().hasSingleBean(ResearchExportRateLimit.class).hasSingleBean(ResearchEvidenceExportService.class);
            assertThat(ctx.getBean(ResearchEvidenceProperties.class).getExportMaxPerWindow()).isEqualTo(3);
            assertThat(ctx.getBean(ResearchEvidenceProperties.class).getExportWindowSeconds()).isEqualTo(90);
        });
    }
    @Test void missingLimitMigrationPreventsOptedInStartup(){
        when(jdbc.queryForList(contains("agent_research_export_limit"))).thenThrow(new DataAccessResourceFailureException("private database details"));
        context().withPropertyValues("agentscope.research.enabled=true","agentscope.research.export-enabled=true","agentscope.research.export-rate-limit-enabled=true")
                .run(ctx->assertThat(ctx.getStartupFailure()).hasRootCauseMessage("请先执行 migration-V35-agent-research-export-limit.sql 再启用导出限流"));
    }
    @Test void invalidLimitsAreRejectedBeforeReadingTheDatabase(){
        for(String value:new String[]{"export-max-per-window=0","export-max-per-window=101","export-window-seconds=0","export-window-seconds=3601"})
            context().withPropertyValues("agentscope.research.enabled=true","agentscope.research.export-enabled=true","agentscope.research.export-rate-limit-enabled=true","agentscope.research."+value)
                    .run(ctx->assertThat(ctx.getStartupFailure()).hasRootCauseMessage("来源导出限流参数超出范围：次数 1—100，时间窗 1—3600 秒"));
        verify(jdbc,never()).queryForList(contains("agent_research_export_limit"));
    }
}
