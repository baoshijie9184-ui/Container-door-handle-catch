package com.ruanzhu.doorhandle.module.ai.workbench;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.agent.*;
import com.ruanzhu.doorhandle.module.ai.journal.AgentJournal;
import com.ruanzhu.doorhandle.module.ai.model.AgentModelService;
import io.agentscope.core.message.ToolUseBlock;
import io.agentscope.core.state.AgentState;
import io.agentscope.core.tool.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import java.nio.file.*;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@EnabledIfSystemProperty(named="doorhandle.provider.fixture",matches=".+")
class LocalConversationModelTaskTest {
    @Test void acceptanceWaitResumeAndCompletionRetainTheFirstDefault() throws Exception {
        var config=new Properties();
        try(var in=Files.newInputStream(Path.of(System.getProperty("doorhandle.provider.fixture")))){config.load(in);}
        String url=config.getProperty("url");
        assertThat(url).matches("jdbc:mysql://127\\.0\\.0\\.1:[0-9]{1,5}/doorhandle_provider_test_[a-f0-9]{12}\\?.*");
        var ds=new DriverManagerDataSource(url,config.getProperty("user"),config.getProperty("password"));
        var store=new WorkbenchStore(new JdbcTemplate(ds),new DataSourceTransactionManager(ds),new ObjectMapper());
        var actor=new AgentActor(4,"alice",AgentActor.Role.INSPECTOR);
        String session=UUID.randomUUID().toString();
        var users=mock(BusinessUserDirectory.class);
        when(users.current(4,"alice")).thenReturn(new BusinessUserDirectory.Identity(4,"alice",false));
        var models=mock(AgentModelService.class);
        var gpt=new AgentModelService.RunModel("openai-official:gpt-fixture",0);
        String qwen="dashscope:qwen-fixture";
        when(models.snapshot("")).thenReturn(gpt,new AgentModelService.RunModel(qwen,0));
        var runs=new AgentRunRegistry();
        var preferences=new ConversationModelPreferences(store,provider(mock(AgentChatSessionApi.class)),runs,models);
        var catalog=Set.of(gpt.id(),qwen);
        String slot=AgentRunRegistry.key(actor,session);
        assertThat(runs.acquire(slot)).isTrue();
        assertThatThrownBy(()->preferences.selectModel(actor,session,qwen,0,"busy-"+session,catalog)).hasMessageContaining("409");
        runs.release(slot);
        try(var work=new AgentWorkbenchService(store,new WorkbenchProperties(),users,provider(mock(WorkbenchSessionApi.class)),
                mock(RoleAgentFactory.class),AgentJournal.disabled())){
            work.setModels(models);
            var initial=work.prepare(actor,session,"分析检测结果","first");
            assertThat(initial.modelId("other")).isEqualTo(gpt.id());
            var tools=new Toolkit();
            initial.install(tools);
            var input=Map.<String,Object>of("title","计划","text","先查看数据");
            tools.getTool("submit_plan").callAsync(ToolCallParam.builder()
                    .toolUseBlock(new ToolUseBlock("plan","submit_plan",input)).input(input).build()).block();
            assertThat(work.waitingPhase(actor,session)).isEqualTo("WAITING_PLAN");
            long sdkRevision=initial.stateStore().saveIfVersion("4",initial.sdkSession(),"agent_state",
                    AgentState.builder().userId("4").sessionId(initial.sdkSession()).build(),0);
            store.create(4,session,WorkbenchStore.stable(4,session,"checkpoint:"+initial.jobId),"CHECKPOINT","SAVED",
                    Map.of("parentId",initial.jobId,"logicalTaskId",initial.contextTask(),"runId","first","phase","AFTER_TOOLS","sdkRevision",sdkRevision));
            initial.release();
            assertThatThrownBy(()->preferences.selectModel(actor,session,qwen,0,"waiting-"+session,catalog)).hasMessageContaining("409");
            var plan=store.rows(4,session,"PLAN","PENDING").get(0);
            work.command(actor,session,plan.id(),plan.revision(),"approve-"+session,"approve-plan",Map.of());
            var resumed=work.prepare(actor,session,"继续","second");
            assertThat(resumed.modelId(qwen)).isEqualTo(gpt.id());
            resumed.finish("COMPLETED","完成");resumed.release();
            assertThat(preferences.selectModel(actor,session,qwen,0,"select-"+session,catalog).modelId()).isEqualTo(qwen);
        }
    }
    private static <T> ObjectProvider<T> provider(T value){
        @SuppressWarnings("unchecked") ObjectProvider<T> result=mock(ObjectProvider.class);
        when(result.getObject()).thenReturn(value);
        return result;
    }
}
