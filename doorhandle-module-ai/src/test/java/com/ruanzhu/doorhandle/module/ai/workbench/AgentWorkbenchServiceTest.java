package com.ruanzhu.doorhandle.module.ai.workbench;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.agent.*;
import com.ruanzhu.doorhandle.module.ai.journal.AgentJournal;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory;
import io.agentscope.core.ReActAgent;
import io.agentscope.core.agent.RuntimeContext;
import io.agentscope.core.message.*;
import io.agentscope.core.model.*;
import io.agentscope.core.state.*;
import io.agentscope.core.tool.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import reactor.core.publisher.*;
import java.nio.file.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@Timeout(60)
class AgentWorkbenchServiceTest {
    final AgentActor alice=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);
    WorkbenchStore store;WorkbenchProperties properties;AgentWorkbenchService service;WorkbenchSessionApi app;BusinessUserDirectory users;RoleAgentFactory factory;com.zaxxer.hikari.HikariDataSource pool;
    @BeforeEach void setup()throws Exception{
        javax.sql.DataSource source=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa","");var jdbc=new JdbcTemplate(source);
        String ddl=Files.readString(Path.of("../sql/mysql/migration-V37-agent-workbench.sql")).replaceAll("(?m)^--.*$", "").replace(" COLLATE utf8mb4_bin","").replace(" ENGINE=InnoDB DEFAULT CHARSET=utf8mb4","")
            .replaceAll("(?m)^(\\s*)UNIQUE KEY (\\w+)\\s*(\\([^\\n]+\\))", "$1CONSTRAINT $2 UNIQUE $3").replaceAll("(?m)^\\s*KEY .*\\n","").replaceAll(",\\s*\\)",")");
        if(Boolean.getBoolean("workbench.mysql")){
            var config=new ObjectMapper().readTree(Path.of("../work/workbench-mysql/connection.json").toFile());String database=config.path("database").asText();
            if(!database.matches("doorhandle_wb_verify_[a-f0-9]{10}")||!config.path("url").asText().startsWith("jdbc:mysql://127.0.0.1:13308/"+database+"?"))throw new IllegalStateException("Only the isolated verification database is allowed");
            pool=new com.zaxxer.hikari.HikariDataSource();pool.setJdbcUrl(config.path("url").asText()+"&connectTimeout=8000&socketTimeout=15000");pool.setUsername(config.path("username").asText());pool.setPassword(config.path("password").asText());pool.setConnectionInitSql("SET time_zone = '+08:00'");pool.setMaximumPoolSize(8);pool.setMinimumIdle(1);source=pool;jdbc=new JdbcTemplate(source);
            assertThat(jdbc.queryForObject("SELECT @@session.time_zone",String.class)).isEqualTo("+08:00");
            for(String table:List.of("agent_workbench_sdk_state","agent_workbench_request","agent_workbench_audit","agent_workbench_item","agent_workbench_owner"))jdbc.execute("DROP TABLE IF EXISTS "+table);
            ddl=Files.readString(Path.of("../sql/mysql/migration-V37-agent-workbench.sql")).replaceAll("(?m)^--.*$", "");
        }
        for(String sql:ddl.split(";"))if(!sql.isBlank())jdbc.execute(sql);
        store=new WorkbenchStore(jdbc,new DataSourceTransactionManager(source),new ObjectMapper());properties=new WorkbenchProperties();properties.setEnabled(true);
        users=mock(BusinessUserDirectory.class);when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",false));
        app=mock(WorkbenchSessionApi.class);var provider=mock(ObjectProvider.class);when(provider.getObject()).thenReturn(app);
        factory=mock(RoleAgentFactory.class);when(factory.definitions(alice)).thenReturn(RoleAgentCatalog.specialists(alice));var journal=mock(AgentJournal.class);when(journal.enabled()).thenReturn(true);
        service=new AgentWorkbenchService(store,properties,users,provider,factory,journal);service.validate();
    }
    @AfterEach void close(){if(service!=null)service.close();if(pool!=null)pool.close();}
    AgentWorkbenchService.Scope scope(String question){return service.prepare(alice,"s1",question,"run-1");}
    @Test void modelSelectionIsOwnedVersionedAndFrozenDuringExecution(){
        assertThat(service.modelSelection(alice,"s1").modelId()).isEmpty();
        String model="deepseek:demo";var selected=service.selectModel(alice,"s1",model,0,"select-1",Set.of(model));
        assertThat(service.selectModel(alice,"s1",model,0,"select-1",Set.of(model))).isEqualTo(selected);
        assertThatThrownBy(()->service.selectModel(alice,"s1","arbitrary:url",selected.revision(),"bad",Set.of(model))).hasMessageContaining("400");
        assertThatThrownBy(()->service.selectModel(alice,"s1","",0,"stale",Set.of(model))).hasMessageContaining("409");
        var scope=scope("查看任务");assertThat(scope.modelId("default")).isEqualTo(model);
        assertThatThrownBy(()->service.selectModel(alice,"s1","",selected.revision(),"active",Set.of(model))).hasMessageContaining("409");
        assertThat(scope.modelId("default")).isEqualTo(model);scope.finish("COMPLETED","完成");scope.release();
        service.selectModel(alice,"s1","",selected.revision(),"select-default",Set.of(model));assertThat(scope("查看模型").modelId("default")).isEqualTo("default");
        doThrow(new org.springframework.security.access.AccessDeniedException("forbidden")).when(app).assertOwned(alice,"foreign");
        assertThatThrownBy(()->service.modelSelection(alice,"foreign")).isInstanceOf(org.springframework.security.access.AccessDeniedException.class);
    }
    private ModelConfigurationApi versionedModels(){
        var configuration=mock(ModelConfigurationApi.class);
        var provider=mock(ObjectProvider.class);when(provider.getIfAvailable()).thenReturn(configuration);when(provider.getObject()).thenReturn(configuration);
        service.setModelConfigurations(provider);return configuration;
    }
    @Test void planContinuationKeepsCapturedModelVersionAfterAnAdministratorPublishes(){
        var configuration=versionedModels();when(configuration.active()).thenReturn(new ModelConfigurationApi.Active(7,"dashscope:old","dashscope:memory"));
        var original=scope("分析任务并生成报告");assertThat(original.modelConfigVersion()).isEqualTo(7);assertThat(original.modelId("fallback")).isEqualTo("dashscope:old");
        call(original,"submit_plan","version-plan",Map.of("title","分析计划","text","先查询再汇总"));
        when(configuration.active()).thenReturn(new ModelConfigurationApi.Active(8,"deepseek:new","dashscope:memory"));
        var plan=item("PLAN");service.command(alice,"s1",plan.id(),plan.revision(),"approve-version-plan","approve-plan",Map.of());
        var continued=service.prepare(alice,"s1","继续已批准计划","version-next-attempt");
        assertThat(continued.modelConfigVersion()).isEqualTo(7);assertThat(continued.modelId("fallback")).isEqualTo("dashscope:old");
        verify(configuration,times(2)).assertTaskConfiguration(7,"dashscope:old");continued.finish("COMPLETED","done");continued.release();
        var next=service.prepare(alice,"s1","查看任务","new-logical-task");assertThat(next.modelConfigVersion()).isEqualTo(8);assertThat(next.modelId("fallback")).isEqualTo("deepseek:new");next.release();
    }
    @Test void invalidRecoveryModelRequiresExplicitSelectionAndDoesNotChangeUnrelatedChildren(){
        var configuration=versionedModels();when(configuration.active()).thenReturn(new ModelConfigurationApi.Active(7,"dashscope:old","dashscope:memory"));
        var original=scope("查看任务");
        original.stateStore().saveIfVersion("1",original.sdkSession(),"agent_state",AgentState.builder().userId("1").sessionId(original.sdkSession()).context(List.of(new UserMessage("checkpoint"))).build(),0);
        original.finish("NEEDS_REVIEW","");original.release();var interrupted=item("EXECUTION");
        var child=store.create(1,"s1",UUID.randomUUID().toString(),"CHILD","NEEDS_REVIEW",Map.of("parentId",interrupted.id(),"parentTaskId",interrupted.data().get("logicalTaskId"),"logicalTaskId","current-child-task","modelConfigVersion",7,"modelDefault","dashscope:old","modelId",""));
        var unrelated=store.create(1,"s1",UUID.randomUUID().toString(),"CHILD","NEEDS_REVIEW",Map.of("parentId",interrupted.id(),"parentTaskId","previous-parent-task","logicalTaskId","previous-child-task","modelConfigVersion",6,"modelDefault","dashscope:older","modelId",""));
        doThrow(new IllegalStateException("credential revoked; choose again")).when(configuration).assertTaskConfiguration(7,"dashscope:old");
        assertThatThrownBy(()->service.command(alice,"s1",interrupted.id(),interrupted.revision(),"invalid-model-resume","resume",Map.of())).hasMessageContaining("choose again");
        assertThat(item("EXECUTION").status()).isEqualTo("NEEDS_REVIEW");
        when(configuration.active()).thenReturn(new ModelConfigurationApi.Active(8,"deepseek:new","dashscope:memory"));
        assertThatThrownBy(()->service.command(alice,"s1",interrupted.id(),interrupted.revision(),"stale-config-resume","resume",Map.of("replacementModelId","","replacementConfigVersion",7))).hasMessageContaining("配置已变化");
        var resumed=service.command(alice,"s1",interrupted.id(),interrupted.revision(),"explicit-new-model","resume",Map.of("replacementModelId","","replacementConfigVersion",8));
        assertThat(resumed.status()).isEqualTo("READY");
        assertThat(((Number)store.require(1,"s1",child.id()).data().get("modelConfigVersion")).longValue()).isEqualTo(8);
        assertThat(((Number)store.require(1,"s1",unrelated.id()).data().get("modelConfigVersion")).longValue()).isEqualTo(6);
        assertThat(new JdbcWorkbenchStateStore(store).exists("1",original.sdkSession())).isTrue();
        assertThat(service.command(alice,"s1",interrupted.id(),interrupted.revision(),"explicit-new-model","resume",Map.of("replacementModelId","","replacementConfigVersion",8))).isEqualTo(resumed);
        assertThat((List<?>)store.require(1,"s1",interrupted.id()).data().get("modelConfigurationHistory")).hasSize(1);
    }
    @Test void separateAccountsAndConversationsKeepIndependentModelChoices(){
        var bob=new AgentActor(2,"bob",AgentActor.Role.SUPERVISOR);
        when(users.current(2,"bob")).thenReturn(new BusinessUserDirectory.Identity(2,"bob",true));
        doAnswer(call->{AgentActor actor=call.getArgument(0);String session=call.getArgument(1);
            if(!(actor.userId()==1&&Set.of("alice-1","alice-2").contains(session))&&!(actor.userId()==2&&session.equals("bob-1")))throw new org.springframework.security.access.AccessDeniedException("private session");return null;
        }).when(app).assertOwned(any(),anyString());
        var configured=Set.of("dashscope:flash","dashscope:max");
        service.selectModel(alice,"alice-1","dashscope:flash",0,"same-request",configured);
        service.selectModel(bob,"bob-1","dashscope:max",0,"same-request",configured);
        assertThat(service.modelSelection(alice,"alice-1").modelId()).isEqualTo("dashscope:flash");
        assertThat(service.modelSelection(alice,"alice-2")).isEqualTo(new AgentWorkbenchService.ModelSelection("",0));
        assertThat(service.modelSelection(bob,"bob-1").modelId()).isEqualTo("dashscope:max");
        assertThatThrownBy(()->service.modelSelection(bob,"alice-1")).isInstanceOf(org.springframework.security.access.AccessDeniedException.class);
        assertThatThrownBy(()->service.selectModel(bob,"alice-1","dashscope:max",1,"cross-account",configured)).isInstanceOf(org.springframework.security.access.AccessDeniedException.class);
        // A fresh execution reads the saved route rather than the global default.
        var scope=service.prepare(alice,"alice-1","查看任务","route-test");
        assertThat(scope.modelId("global-default")).isEqualTo("dashscope:flash");scope.finish("COMPLETED","done");scope.release();
        assertThat(service.modelSelection(bob,"bob-1").modelId()).isEqualTo("dashscope:max");
    }
    @Test void unapprovedPlanDoesNotAdvertiseProfessionalOrArtifactTools(){
        var scope=scope("查询任务，不修改或审批");var toolkit=new Toolkit();
        var delegate=mock(AgentTool.class);when(delegate.getName()).thenReturn("delegate_detection_quality");toolkit.registerAgentTool(delegate);scope.install(toolkit);
        assertThat(toolkit.getToolNames()).contains("submit_plan","read_workspace_file").doesNotContain("delegate_detection_quality","start_background_task","create_artifact");
        assertThat(scope.prompt()).contains("第一步调用 submit_plan");
    }
    @Test void backgroundTaskSchemaOnlyAdvertisesCurrentRoleAndItsCapabilities(){
        var toolkit=new Toolkit();scope("查询本人任务").install(toolkit);
        var schema=toolkit.getTool("start_background_task").getParameters();
        assertThat(schema.get("required")).isEqualTo(List.of("specialist","question"));
        var props=(Map<?,?>)schema.get("properties");var specialist=(Map<?,?>)props.get("specialist");
        assertThat(specialist.get("enum")).isEqualTo(factory.definitions(alice).stream().map(RoleAgentCatalog.Definition::id).toList());
        assertThat((String)specialist.get("description")).contains("get_task_detail","detection-task").doesNotContain("department-analytics","propose_quality_assignment");
    }
    @Test void springRepositoryProxySupportsStartupQueriesPlansAndSdkState(){
        var target=store;
        try(var context=new org.springframework.context.support.GenericApplicationContext()){
            context.registerBean(org.springframework.dao.annotation.PersistenceExceptionTranslationPostProcessor.class);
            context.registerBean(WorkbenchStore.class,()->target);
            context.refresh();store=context.getBean(WorkbenchStore.class);
            assertThat(org.springframework.aop.support.AopUtils.isCglibProxy(store)).isTrue();
            var provider=mock(ObjectProvider.class);when(provider.getObject()).thenReturn(app);var journal=mock(AgentJournal.class);when(journal.enabled()).thenReturn(true);
            service.close();service=new AgentWorkbenchService(store,properties,users,provider,factory,journal);service.validate();
            var scope=scope("分析任务并生成文件");call(scope,"submit_plan","proxy-plan",Map.of("title","代理环境计划","text","先审阅再执行"));
            assertThat(item("PLAN").status()).isEqualTo("PENDING");
            var sdk=new JdbcWorkbenchStateStore(store);var state=AgentState.builder().userId("1").sessionId("proxy-sdk").context(List.of(new UserMessage("persistent"))).build();
            assertThat(sdk.saveIfVersion("1","proxy-sdk","agent_state",state,0)).isEqualTo(1);
            assertThat(sdk.getVersioned("1","proxy-sdk","agent_state",AgentState.class).value()).isNotNull();
            service.recoverStale();
        }
    }
    @Test void onlyClearReadQueriesBypassPlanReviewAndCombinedOrArtifactRequestsDoNot(){assertThat(AgentWorkbenchService.simple("查看本人报告")).isTrue();assertThat(AgentWorkbenchService.simple("查询任务并导出 CSV")).isFalse();assertThat(AgentWorkbenchService.simple("列出任务然后分配质检")).isFalse();assertThat(AgentWorkbenchService.simple("请处理这个批次")).isFalse();assertThat(AgentWorkbenchService.simple("/plan 查看任务")).isFalse();}
    AgentWorkbenchApi.Item item(String kind){return service.list(alice,"s1").stream().filter(value->value.kind().equals(kind)).findFirst().orElseThrow();}
    ToolResultBlock call(AgentWorkbenchService.Scope scope,String tool,String id,Map<String,Object> input){var toolkit=new Toolkit();scope.install(toolkit);var result=toolkit.getTool(tool).callAsync(ToolCallParam.builder().toolUseBlock(new ToolUseBlock(id,tool,input)).input(input).build()).block();if(scope.waiting())scope.release();return result;}
    @Test void planApprovalIsVersionedIdempotentAndDoesNotGrantBusinessAuthority(){
        var scope=scope("分析检测情况并生成报告");call(scope,"submit_plan","plan-1",Map.of("title","分析计划","text","先查询再汇总"));
        assertThat(service.waitingPhase(alice,"s1")).isEqualTo("WAITING_PLAN");var plan=item("PLAN");String request=UUID.randomUUID().toString();
        var approved=service.command(alice,"s1",plan.id(),plan.revision(),request,"approve-plan",Map.of());assertThat(approved.status()).isEqualTo("APPROVED");
        assertThat(service.command(alice,"s1",plan.id(),plan.revision(),request,"approve-plan",Map.of())).isEqualTo(approved);
        assertThatThrownBy(()->service.command(alice,"s1",plan.id(),plan.revision(),UUID.randomUUID().toString(),"cancel",Map.of())).hasMessageContaining("409");
        assertThat(store.jdbc().queryForObject("SELECT COUNT(*) FROM agent_workbench_audit WHERE action='APPROVE_PLAN'",Integer.class)).isEqualTo(1);
        assertThat(service.canDispatchInput(alice,"s1","unrelated-message")).isFalse();
        verify(app,never()).continueSession(any(),anyString(),anyString(),anyString());
    }
    @Test void questionChoicesAreValidatedAndAnswerCanOnlySettleOnce(){
        var scope=scope("查看任务");call(scope,"ask_user_question","question-1",Map.of("text","选择时间范围","questionType","SINGLE","options",List.of("今天","本周")));var question=item("QUESTION");
        assertThatThrownBy(()->service.command(alice,"s1",question.id(),0,UUID.randomUUID().toString(),"answer",Map.of("answer","去年"))).hasMessageContaining("400");
        assertThat(service.command(alice,"s1",question.id(),0,UUID.randomUUID().toString(),"answer",Map.of("answer","本周")).status()).isEqualTo("ANSWERED");
        assertThatThrownBy(()->service.command(alice,"s1",question.id(),0,UUID.randomUUID().toString(),"answer",Map.of("answer","今天"))).hasMessageContaining("409");
        assertThat(store.jdbc().queryForList("SELECT * FROM agent_workbench_audit").toString()).doesNotContain("选择时间范围","本周");
    }
    @Test void cancellingAQuestionDoesNotGuessAnAnswerOrContinueTheParent(){
        var scope=scope("查看任务");call(scope,"ask_user_question","question-1",Map.of("text","哪个批次","questionType","TEXT"));var question=item("QUESTION");
        service.command(alice,"s1",question.id(),0,UUID.randomUUID().toString(),"cancel",Map.of());assertThat(item("EXECUTION").status()).isEqualTo("CANCELLED");service.dispatch();verify(app,never()).continueSession(any(),anyString(),anyString(),anyString());
    }
    @Test void revokedIdentityCannotAnswerOrReadPrivateItems(){
        var scope=scope("查看任务");call(scope,"ask_user_question","q",Map.of("text","批次","questionType","TEXT"));var question=item("QUESTION");when(users.current(1,"alice")).thenThrow(new SecurityException());
        assertThatThrownBy(()->service.list(alice,"s1")).isInstanceOf(SecurityException.class);assertThatThrownBy(()->service.command(alice,"s1",question.id(),0,UUID.randomUUID().toString(),"answer",Map.of("answer","A"))).isInstanceOf(SecurityException.class);
    }
    @Test void sdkStateStorePersistsTypedStateAndRejectsStaleCasAcrossInstances(){
        var first=new JdbcWorkbenchStateStore(store);var second=new JdbcWorkbenchStateStore(store);var state=AgentState.builder().userId("1").sessionId("sdk-session").context(List.of(new UserMessage("PRIVATE_STATE"))).build();
        assertThat(first.saveIfVersion("1","sdk-session","agent_state",state,0)).isEqualTo(1);assertThat(second.getVersioned("1","sdk-session","agent_state",AgentState.class).value().getContext().get(0).getTextContent()).isEqualTo("PRIVATE_STATE");
        assertThat(second.saveIfVersion("1","sdk-session","agent_state",state,0)).isEqualTo(AgentStateStore.UNVERSIONED);assertThat(second.get("2","sdk-session","agent_state",AgentState.class)).isEmpty();assertThatThrownBy(()->first.exists(null,"sdk-session")).isInstanceOf(SecurityException.class);
    }
    @Test void completedToolResultIsReusedAfterReloadWithoutReexecutingItsBody(){
        var scope=scope("查看任务");var calls=new AtomicInteger();AgentTool underlying=new AgentTool(){public String getName(){return "lookup";}public String getDescription(){return "read";}public boolean isReadOnly(){return true;}public Map<String,Object>getParameters(){return Map.of();}public Mono<ToolResultBlock>callAsync(ToolCallParam param){calls.incrementAndGet();return Mono.just(ToolResultBlock.text("fact"));}};
        var wrapped=scope.wrap(underlying);var request=ToolCallParam.builder().toolUseBlock(new ToolUseBlock("same-call","lookup",Map.of())).input(Map.of()).build();
        assertThat(wrapped.callAsync(request).block().getOutput()).hasSize(1);assertThat(wrapped.callAsync(request).block().getOutput()).hasSize(1);assertThat(calls.get()).isEqualTo(1);
    }
    @Test void sdkFinalSaveAcceptsItsOwnCheckpointVersionsButNeverOverwritesAnotherAttempt(){
        var state=AgentState.builder().userId("1").sessionId("cas-slot").context(List.of(new UserMessage("state"))).build();var sdk=new JdbcWorkbenchStateStore(store,true);
        assertThat(sdk.saveIfVersion("1","cas-slot","agent_state",state,0)).isEqualTo(1);assertThat(sdk.saveIfVersion("1","cas-slot","agent_state",state,1)).isEqualTo(2);
        assertThat(sdk.saveIfVersion("1","cas-slot","agent_state",state,0)).as("SDK final save still holds its initial call version").isEqualTo(3);
        var other=new JdbcWorkbenchStateStore(store);assertThat(other.saveIfVersion("1","cas-slot","agent_state",state,3)).isEqualTo(4);
        assertThatThrownBy(()->sdk.saveIfVersion("1","cas-slot","agent_state",state,0)).hasMessageContaining("其他执行");assertThatThrownBy(()->sdk.save("1","cas-slot","agent_state",state)).hasMessageContaining("无版本");assertThat(other.getVersioned("1","cas-slot","agent_state",AgentState.class).version()).isEqualTo(4);
    }
    @Test void usageSummaryIncludesOldAttemptsAndKeepsMissingProviderUsageUnknown(){
        store.create(1,"s1",UUID.randomUUID().toString(),"USAGE","COMPLETED",Map.of("inputTokens",20,"outputTokens",4,"modelId","primary","durationMs",100));store.create(1,"s1",UUID.randomUUID().toString(),"USAGE","FAILED",Map.of("modelId","backup","durationMs",50));
        var summary=service.list(alice,"s1").stream().filter(row->"SESSION_TOTAL".equals(row.data().get("purpose"))).findFirst().orElseThrow();assertThat(summary.data().get("inputTokens")).isNull();assertThat(summary.data().get("text").toString()).contains("共 2 次","输入 20","不按零计算");
    }
    @Test void unknownWriteBlocksRecoveryAndNeverReexecutesTheTool(){
        var scope=scope("查看任务");AgentTool underlying=mock(AgentTool.class);when(underlying.getName()).thenReturn("save_draft");when(underlying.getParameters()).thenReturn(Map.of());when(underlying.callAsync(any())).thenReturn(Mono.error(new IllegalStateException("lost-result")));
        var wrapped=scope.wrap(underlying);var input=ToolCallParam.builder().toolUseBlock(new ToolUseBlock("write-1","save_draft",Map.of())).input(Map.of()).build();assertThatThrownBy(()->wrapped.callAsync(input).block()).hasMessageContaining("lost-result");scope.finish("NEEDS_REVIEW","");var job=item("EXECUTION");
        assertThatThrownBy(()->service.command(alice,"s1",job.id(),job.revision(),UUID.randomUUID().toString(),"resume",Map.of())).hasMessageContaining("未知");assertThatThrownBy(()->wrapped.callAsync(input).block()).hasMessageContaining("执行尝试");verify(underlying,times(1)).callAsync(any());
    }
    @Test void auditFailureRollsBackInteractionStateAndRequestReceipt(){
        var scope=scope("查看任务");call(scope,"ask_user_question","q",Map.of("text","批次","questionType","TEXT"));var question=item("QUESTION");store.jdbc().execute("ALTER TABLE agent_workbench_audit ADD CONSTRAINT deny_answer CHECK(action<>'ANSWER')");
        assertThatThrownBy(()->service.command(alice,"s1",question.id(),0,UUID.randomUUID().toString(),"answer",Map.of("answer","PRIVATE"))).isInstanceOf(org.springframework.dao.DataAccessException.class);assertThat(item("QUESTION").status()).isEqualTo("PENDING");assertThat(store.jdbc().queryForObject("SELECT COUNT(*) FROM agent_workbench_request",Integer.class)).isZero();
    }
    @Test void realSdkYieldsAtQuestionAndResumesFromPersistedContext(){
        var scope=scope("查看任务");var model=mock(Model.class);when(model.getModelName()).thenReturn("scripted");var count=new AtomicInteger();when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->count.getAndIncrement()==0?Flux.just(ChatResponse.builder().content(List.of(new ToolUseBlock("q1","ask_user_question",Map.of("text","哪个批次","questionType","TEXT")))).finishReason("tool_calls").build()):Flux.just(ChatResponse.builder().content(List.of(TextBlock.builder().text("最终回答").build())).build()));
        var toolkit=new Toolkit();scope.install(toolkit);var agent=ReActAgent.builder().name("employee-main").model(model).toolkit(toolkit).middlewares(List.of(scope)).stateStore(scope.stateStore()).defaultSessionId(scope.sdkSession()).enableMetaTool(false).enableTaskList(false).build();
        var runtime=RuntimeContext.builder().userId("1").sessionId(scope.sdkSession()).build();
        try{assertThatThrownBy(()->agent.call(List.of(new UserMessage("查看任务")),runtime).block(Duration.ofSeconds(30))).isInstanceOf(AgentWorkbenchService.Yield.class);assertThat(count.get()).isEqualTo(1);}finally{agent.close();scope.release();}
        var question=item("QUESTION");service.command(alice,"s1",question.id(),question.revision(),UUID.randomUUID().toString(),"answer",Map.of("answer","batch-A"));var resumed=service.prepare(alice,"s1","用户回答 batch-A","run-2");
        var nextTools=new Toolkit();resumed.install(nextTools);var next=ReActAgent.builder().name("employee-main").model(model).toolkit(nextTools).middlewares(List.of(resumed)).stateStore(resumed.stateStore()).defaultSessionId(resumed.sdkSession()).enableMetaTool(false).enableTaskList(false).build();
        try{assertThat(next.call(resumed.messages(List.of(new UserMessage("用户回答 batch-A"))),RuntimeContext.builder().userId("1").sessionId(resumed.sdkSession()).build()).block(Duration.ofSeconds(30)).getTextContent()).isEqualTo("最终回答");}finally{next.close();resumed.release();}
    }
    @Test void actualHarnessFacadeYieldsForPlanAndContinuesTheSameLogicalTask()throws Exception{
        var model=mock(Model.class);when(model.getModelName()).thenReturn("scripted");var calls=new AtomicInteger();when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->calls.getAndIncrement()==0?Flux.just(ChatResponse.builder().content(List.of(new ToolUseBlock("plan-tool","submit_plan",Map.of("title","检测分析计划","text","查询任务再整理报告")))).finishReason("tool_calls").build()):Flux.just(ChatResponse.builder().content(List.of(TextBlock.builder().text("已按计划完成分析").build())).finishReason("stop").build()));
        var runtimeProperties=new AgentScopeProperties();runtimeProperties.setWorkspace(Files.createTempDirectory(Path.of("target"),"workbench-harness-").toString());var toolkits=mock(BusinessToolkitFactory.class);var roles=new RoleAgentFactory(runtimeProperties,toolkits,id->model);
        var journal=mock(AgentJournal.class);when(journal.enabled()).thenReturn(true);when(journal.begin(any(),anyString(),anyString(),anyString(),anyString(),anyString())).thenAnswer(inv->{var run=mock(AgentJournal.Run.class);when(run.id()).thenReturn(UUID.randomUUID().toString());return run;});
        var facade=new com.ruanzhu.doorhandle.module.ai.service.AgentScopeConversationService(roles,new AgentRunRegistry(),runtimeProperties,journal);facade.setWorkbench(service);
        var first=facade.start(alice,"s1",List.of(new AgentConversationApi.Message("user","分析检测情况并生成报告")),"",event->{});
        assertThat(first.result().get(30,TimeUnit.SECONDS)).contains("计划已保存");org.awaitility.Awaitility.await().atMost(Duration.ofSeconds(15)).until(()->Boolean.TRUE.equals(store.require(1,"s1",item("EXECUTION").id()).data().get("yieldReady")));
        var plan=item("PLAN");String originalTask=(String)store.require(1,"s1",item("EXECUTION").id()).data().get("logicalTaskId");service.command(alice,"s1",plan.id(),plan.revision(),UUID.randomUUID().toString(),"approve-plan",Map.of());
        var second=facade.start(alice,"s1",List.of(new AgentConversationApi.Message("user","按已批准的计划继续")),"",event->{});assertThat(second.result().get(30,TimeUnit.SECONDS)).isEqualTo("已按计划完成分析");assertThat(calls.get()).isEqualTo(2);assertThat(store.require(1,"s1",item("EXECUTION").id()).data().get("logicalTaskId")).isEqualTo(originalTask);
    }
    @Test void completedTaskRetainsItsResultDespiteLateCancellationOrCleanupFailure(){
        var completed=scope("查看任务");completed.finish("COMPLETED","original result");var saved=item("EXECUTION");
        completed.cancel();completed.finish("NEEDS_REVIEW","");completed.finish("COMPLETED","late result");
        var current=item("EXECUTION");assertThat(current.status()).isEqualTo("COMPLETED");assertThat(current.revision()).isEqualTo(saved.revision());assertThat(current.data().get("result")).isEqualTo("original result");completed.release();
    }
    @Test void oldAttemptCannotOverwriteANewerTaskAndEachNewTaskHasItsOwnSdkSlot(){
        var first=scope("查看任务");String previous=first.sdkSession();first.finish("COMPLETED","done");first.release();var second=service.prepare(alice,"s1","查看报告","run-2");first.finish("NEEDS_REVIEW","");
        assertThat(second.sdkSession()).isNotEqualTo(previous);assertThat(first.sdkSession()).isEqualTo(previous);assertThat(item("EXECUTION").status()).isEqualTo("RUNNING");second.release();
    }
    @Test void staleRemoteExecutionBecomesReviewableButLocalHeartbeatKeepsItsLease(){
        var local=scope("查看任务");store.jdbc().update("UPDATE agent_workbench_item SET updated_at=? WHERE item_id=?",store.jdbc().queryForObject("SELECT CURRENT_TIMESTAMP(6)",java.time.LocalDateTime.class).minusMinutes(5),item("EXECUTION").id());service.recoverStale();assertThat(item("EXECUTION").status()).isEqualTo("RUNNING");
        local.release();store.jdbc().update("UPDATE agent_workbench_item SET updated_at=? WHERE item_id=?",store.jdbc().queryForObject("SELECT CURRENT_TIMESTAMP(6)",java.time.LocalDateTime.class).minusMinutes(5),item("EXECUTION").id());service.recoverStale();assertThat(item("EXECUTION").status()).isEqualTo("NEEDS_REVIEW");
        var interrupted=item("EXECUTION");assertThatThrownBy(()->service.command(alice,"s1",interrupted.id(),interrupted.revision(),UUID.randomUUID().toString(),"resume",Map.of())).hasMessageContaining("检查点");
    }
    @Test void answeringBeforeSdkHasCommittedItsWaitIsRejected(){
        var scope=scope("查看任务");var toolkit=new Toolkit();scope.install(toolkit);toolkit.getTool("ask_user_question").callAsync(ToolCallParam.builder().toolUseBlock(new ToolUseBlock("q","ask_user_question",Map.of("text","批次","questionType","TEXT"))).input(Map.of("text","批次","questionType","TEXT")).build()).block();var question=item("QUESTION");
        assertThatThrownBy(()->service.command(alice,"s1",question.id(),0,UUID.randomUUID().toString(),"answer",Map.of("answer","A"))).hasMessageContaining("等待状态");scope.release();assertThat(service.command(alice,"s1",question.id(),0,UUID.randomUUID().toString(),"answer",Map.of("answer","A")).status()).isEqualTo("ANSWERED");
    }
    @Test @Timeout(120) void specialistKeepsHistoryForFollowUpAndWakesOnlyItsOwnParent()throws Exception{
        service.close();var model=mock(Model.class);when(model.getModelName()).thenReturn("scripted-child");var observed=new CopyOnWriteArrayList<List<Msg>>();
        when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{observed.add(List.copyOf(inv.getArgument(0)));return Flux.just(ChatResponse.builder().content(List.of(TextBlock.builder().text("专业分析已完成").build())).build());});
        var toolkits=mock(BusinessToolkitFactory.class);when(toolkits.create(any(),any(),anyString())).thenAnswer(inv->new Toolkit());var roles=new RoleAgentFactory(new AgentScopeProperties(),toolkits,id->model);
        String journalDdl=Files.readString(Path.of("src/main/resources/db/migration-V16-agentscope-run-journal.sql"));
        if(!Boolean.getBoolean("workbench.mysql"))journalDdl=journalDdl.replace(" COLLATE utf8mb4_bin","").replace(" ENGINE=InnoDB DEFAULT CHARSET=utf8mb4","").replace("payload_json JSON","payload_json VARCHAR(8192)");
        for(String statement:journalDdl.split(";"))if(!statement.isBlank())store.jdbc().execute(statement);
        var journalSettings=new com.ruanzhu.doorhandle.module.ai.config.AgentJournalProperties();journalSettings.setEnabled(true);
        var journal=new com.ruanzhu.doorhandle.module.ai.journal.JdbcAgentJournal(store.jdbc(),new DataSourceTransactionManager(store.jdbc().getDataSource()),new ObjectMapper(),journalSettings);journal.verifySchema();
        var provider=mock(ObjectProvider.class);when(provider.getObject()).thenReturn(app);service=new AgentWorkbenchService(store,properties,users,provider,roles,journal);
        var main=scope("查看任务");call(main,"start_background_task","child-1",Map.of("specialist","detection-task","question","查询批次 A"));service.dispatch();
        org.awaitility.Awaitility.await().atMost(Duration.ofSeconds(30)).until(()->item("CHILD").status().equals("COMPLETED")&&item("EXECUTION").status().equals("READY"));
        var child=item("CHILD");service.command(alice,"s1",child.id(),child.revision(),UUID.randomUUID().toString(),"child-message",Map.of("content","再补充缺陷类型"));service.dispatch();
        org.awaitility.Awaitility.await().atMost(Duration.ofSeconds(30)).until(()->item("CHILD").status().equals("COMPLETED")&&Boolean.TRUE.equals(store.require(1,"s1",item("CHILD").id()).data().get("yieldReady")));
        assertThat(observed).hasSize(2);assertThat(observed.get(1).stream().map(Msg::getTextContent).toList()).anyMatch(text->text!=null&&text.contains("查询批次 A")).anyMatch(text->text!=null&&text.contains("再补充缺陷类型"));
        var subscribed=new java.util.concurrent.atomic.AtomicBoolean();var cancelled=new java.util.concurrent.atomic.AtomicBoolean();when(model.stream(anyList(),anyList(),any())).thenReturn(Flux.<ChatResponse>never().doOnSubscribe(value->subscribed.set(true)).doOnCancel(()->cancelled.set(true)));
        child=item("CHILD");service.command(alice,"s1",child.id(),child.revision(),UUID.randomUUID().toString(),"child-message",Map.of("content","继续核对"));service.dispatch();org.awaitility.Awaitility.await().atMost(Duration.ofSeconds(30)).untilTrue(subscribed);
        child=item("CHILD");String cancelledRun=(String)child.data().get("runId");service.command(alice,"s1",child.id(),child.revision(),UUID.randomUUID().toString(),"cancel",Map.of());org.awaitility.Awaitility.await().atMost(Duration.ofSeconds(15)).untilTrue(cancelled);assertThat(item("CHILD").status()).isEqualTo("CANCELLED");
        org.awaitility.Awaitility.await().atMost(Duration.ofSeconds(15)).until(()->journal.get(alice,cancelledRun).status().equals("CANCELLED"));
        assertThat(journal.list(alice,"child-"+child.id(),null,20)).hasSize(3).allSatisfy(run->assertThat(run.entryPoint()).isEqualTo("CHILD"));
    }
    @Test void cancellingOneChildLeavesItsSiblingAndParentWaiting(){
        var main=scope("查看任务");call(main,"start_background_task","child-1",Map.of("specialist","detection-task","question","批次 A"));
        // A second child may already have been admitted in the same SDK batch.
        var parent=store.require(1,"s1",item("EXECUTION").id());String second=UUID.randomUUID().toString();store.create(1,"s1",second,"CHILD","QUEUED",Map.of("parentId",parent.id(),"parentTaskId",parent.data().get("logicalTaskId"),"logicalTaskId",UUID.randomUUID().toString(),"specialist","quality-review"));
        var first=service.list(alice,"s1").stream().filter(row->row.kind().equals("CHILD")&&!row.id().equals(second)).findFirst().orElseThrow();service.command(alice,"s1",first.id(),first.revision(),UUID.randomUUID().toString(),"cancel",Map.of());assertThat(store.require(1,"s1",second).status()).isEqualTo("QUEUED");assertThat(item("EXECUTION").status()).isEqualTo("WAITING_CHILD");
        var current=item("EXECUTION");service.command(alice,"s1",current.id(),current.revision(),UUID.randomUUID().toString(),"cancel",Map.of());assertThat(store.require(1,"s1",second).status()).isEqualTo("CANCELLED");
    }
    @Test void additionalRequirementsQueueDuringActiveChildAndKeepTheSameSdkHistory(){
        var main=scope("查看任务");call(main,"start_background_task","child-1",Map.of("specialist","detection-task","question","批次 A"));var child=item("CHILD");var data=new LinkedHashMap<>(store.require(1,"s1",child.id()).data());data.put("runId","child-attempt");store.update(store.require(1,"s1",child.id()),"RUNNING",data,"TEST_CHILD_RUNNING");
        child=item("CHILD");service.command(alice,"s1",child.id(),child.revision(),"followup-1","child-message",Map.of("content","补充缺陷类型"));assertThat(item("CHILD").status()).isEqualTo("RUNNING");
        var active=service.new Scope(alice,"s1",child.id(),"child-attempt","detection-task");String sdk=active.sdkSession();active.finish("COMPLETED","第一阶段结果");var queued=store.require(1,"s1",child.id());assertThat(queued.status()).isEqualTo("QUEUED");assertThat(queued.data().get("question")).isEqualTo("补充缺陷类型");assertThat(active.sdkSession()).isEqualTo(sdk);
    }
    @Test void anOldInteractionCannotAnswerOrCancelALaterTaskInTheSameConversation(){
        var first=scope("查看任务");call(first,"ask_user_question","q1",Map.of("text","旧批次","questionType","TEXT"));var old=item("QUESTION");var job=item("EXECUTION");service.command(alice,"s1",job.id(),job.revision(),"cancel-old","cancel",Map.of());assertThat(store.require(1,"s1",old.id()).status()).isEqualTo("CANCELLED");
        var next=service.prepare(alice,"s1","查看报告","run-2");call(next,"ask_user_question","q2",Map.of("text","新批次","questionType","TEXT"));var stale=store.require(1,"s1",old.id());
        assertThatThrownBy(()->service.command(alice,"s1",old.id(),stale.revision(),"answer-old","answer",Map.of("answer","wrong"))).hasMessageContaining("409");assertThatThrownBy(()->service.command(alice,"s1",old.id(),stale.revision(),"cancel-old-question","cancel",Map.of())).hasMessageContaining("409");assertThat(item("EXECUTION").status()).isEqualTo("WAITING_INPUT");
    }
    @Test void providerCallIdsCanRepeatInDifferentLogicalTasksWithoutReusingOldResults(){
        var calls=new AtomicInteger();AgentTool tool=new AgentTool(){public String getName(){return "lookup";}public String getDescription(){return "read";}public boolean isReadOnly(){return true;}public Map<String,Object>getParameters(){return Map.of();}public Mono<ToolResultBlock>callAsync(ToolCallParam input){return Mono.just(ToolResultBlock.text("result-"+calls.incrementAndGet()));}};
        var input=ToolCallParam.builder().toolUseBlock(new ToolUseBlock("call-1","lookup",Map.of())).input(Map.of()).build();var first=scope("查看任务");first.wrap(tool).callAsync(input).block();first.finish("COMPLETED","done");first.release();var next=service.prepare(alice,"s1","查看任务","run-2");next.wrap(tool).callAsync(input).block();assertThat(calls.get()).isEqualTo(2);next.release();
    }
    @Test void cancellingAChildQuestionUnblocksTheWaitingParentWithoutGuessingTheAnswer(){
        var main=scope("查看任务");call(main,"start_background_task","child-1",Map.of("specialist","detection-task","question","批次 A"));var child=item("CHILD");var data=new LinkedHashMap<>(store.require(1,"s1",child.id()).data());data.put("runId","child-run");store.update(store.require(1,"s1",child.id()),"RUNNING",data,"TEST_STARTED");
        var specialist=service.new Scope(alice,"s1",child.id(),"child-run","detection-task");call(specialist,"ask_user_question","child-question",Map.of("text","缺少批次编号","questionType","TEXT"));var question=item("QUESTION");service.command(alice,"s1",question.id(),question.revision(),"cancel-question","cancel",Map.of());assertThat(store.require(1,"s1",child.id()).status()).isEqualTo("CANCELLED");assertThat(item("EXECUTION").status()).isEqualTo("READY");
    }
    @Test @Timeout(180) @org.junit.jupiter.api.condition.EnabledIfSystemProperty(named="workbench.mysql",matches="true")
    void processDeathAfterCompletedToolRestoresSdkWithoutRepeatingTheEffect()throws Exception{crashAndRecover("completed",24);}
    @Test @Timeout(180) @org.junit.jupiter.api.condition.EnabledIfSystemProperty(named="workbench.mysql",matches="true")
    void processDeathInsideWriteLeavesUnknownReceiptAndCannotBeReplayed()throws Exception{crashAndRecover("unknown",23);}
    @org.junit.jupiter.params.ParameterizedTest @org.junit.jupiter.params.provider.ValueSource(strings={"before-model","before-effect","waiting","child"})
    @Timeout(75) @org.junit.jupiter.api.condition.EnabledIfSystemProperty(named="workbench.mysql",matches="true")
    void processDeathAtOtherBoundariesRequiresExplicitContinuationAndDoesNotInventEffects(String scenario)throws Exception{
        haltProcess(scenario,Map.of("before-model",25,"before-effect",26,"waiting",27,"child",28).get(scenario));store.jdbc().update("UPDATE agent_workbench_item SET updated_at=? WHERE kind IN ('EXECUTION','CHILD')",store.jdbc().queryForObject("SELECT CURRENT_TIMESTAMP(6)",java.time.LocalDateTime.class).minusMinutes(5));service.recoverStale();
        if(scenario.equals("waiting")){assertThat(item("EXECUTION").status()).isEqualTo("WAITING_INPUT");var question=item("QUESTION");service.command(alice,"s1",question.id(),question.revision(),"answer-after-restart","answer",Map.of("answer","batch-A"));assertThat(item("EXECUTION").status()).isEqualTo("READY");}
        else if(scenario.equals("child")){assertThat(item("EXECUTION").status()).isEqualTo("WAITING_CHILD");var child=item("CHILD");assertThat(child.status()).isEqualTo("NEEDS_REVIEW");service.command(alice,"s1",child.id(),child.revision(),"resume-child","resume",Map.of());assertThat(item("CHILD").status()).isEqualTo("QUEUED");}
        else{var job=item("EXECUTION");assertThat(job.status()).isEqualTo("NEEDS_REVIEW");if(scenario.equals("before-effect"))assertThatThrownBy(()->service.command(alice,"s1",job.id(),job.revision(),"resume-no-proof","resume",Map.of())).hasMessageContaining("未知");else{service.command(alice,"s1",job.id(),job.revision(),"resume-model","resume",Map.of());assertThat(item("EXECUTION").status()).isEqualTo("READY");}}
        assertThat(store.jdbc().queryForObject("SELECT COUNT(*) FROM agent_workbench_crash_effect",Integer.class)).isZero();verify(app,never()).continueSession(any(),anyString(),anyString(),anyString());
    }
    private void haltProcess(String scenario,int expectedExit)throws Exception{
        store.jdbc().execute("DROP TABLE IF EXISTS agent_workbench_crash_effect");store.jdbc().execute("CREATE TABLE agent_workbench_crash_effect(id BIGINT PRIMARY KEY)");
        String javaExecutable=Path.of(System.getProperty("java.home"),"bin",System.getProperty("os.name").toLowerCase(Locale.ROOT).contains("win")?"java.exe":"java").toString();String classpath=System.getProperty("surefire.test.class.path",System.getProperty("java.class.path"));
        var process=new ProcessBuilder(javaExecutable,"-cp",classpath,WorkbenchCrashProbe.class.getName(),scenario).redirectErrorStream(true).redirectOutput(Path.of("../work/workbench-mysql/crash-"+scenario+".log").toFile()).start();
        try{assertThat(process.waitFor(55,TimeUnit.SECONDS)).as("isolated JVM must exit at the injection point").isTrue();assertThat(process.exitValue()).isEqualTo(expectedExit);}finally{if(process.isAlive()){process.destroyForcibly();process.waitFor(10,TimeUnit.SECONDS);}}
    }
    private void crashAndRecover(String scenario,int expectedExit)throws Exception{
        haltProcess(scenario,expectedExit);
        store.jdbc().update("UPDATE agent_workbench_item SET updated_at=? WHERE kind='EXECUTION'",store.jdbc().queryForObject("SELECT CURRENT_TIMESTAMP(6)",java.time.LocalDateTime.class).minusMinutes(5));service.recoverStale();var interrupted=item("EXECUTION");assertThat(interrupted.status()).isEqualTo("NEEDS_REVIEW");
        if(scenario.equals("unknown")){assertThatThrownBy(()->service.command(alice,"s1",interrupted.id(),interrupted.revision(),UUID.randomUUID().toString(),"resume",Map.of())).hasMessageContaining("未知");assertThat(item("EXECUTION").status()).isEqualTo("NEEDS_REVIEW");assertThat(store.jdbc().queryForObject("SELECT status FROM agent_workbench_item WHERE kind='TOOL'",String.class)).isEqualTo("UNKNOWN");verify(app,never()).continueSession(any(),anyString(),anyString(),anyString());}
        else resumeKnownEffectThroughOneWinningSdkExecution(interrupted);
        assertThat(store.jdbc().queryForObject("SELECT COUNT(*) FROM agent_workbench_crash_effect",Integer.class)).isEqualTo(1);
    }
    private void resumeKnownEffectThroughOneWinningSdkExecution(AgentWorkbenchApi.Item interrupted)throws Exception{
        String originalReceipt=store.jdbc().queryForObject("SELECT payload FROM agent_workbench_item WHERE kind='TOOL'",String.class);
        var journal=mock(AgentJournal.class);when(journal.enabled()).thenReturn(true);var provider=mock(ObjectProvider.class);when(provider.getObject()).thenReturn(app);
        var other=new AgentWorkbenchService(new WorkbenchStore(store.jdbc(),new DataSourceTransactionManager(pool),new ObjectMapper()),properties,users,provider,factory,journal);
        var racers=Executors.newFixedThreadPool(2);
        try{
            var gate=new CountDownLatch(1);var statuses=new CopyOnWriteArrayList<String>();
            var requests=new ArrayList<Future<?>>();
            for(var candidate:List.of(service,other))requests.add(racers.submit(()->{gate.await();try{statuses.add(candidate.command(alice,"s1",interrupted.id(),interrupted.revision(),UUID.randomUUID().toString(),"resume",Map.of()).status());}catch(org.springframework.web.server.ResponseStatusException conflict){assertThat(conflict.getStatusCode().value()).isEqualTo(409);statuses.add("CONFLICT");}return null;}));
            gate.countDown();for(var request:requests)request.get(30,TimeUnit.SECONDS);assertThat(statuses).containsExactlyInAnyOrder("READY","CONFLICT");
            var admissionGate=new CountDownLatch(1);var admitted=new CopyOnWriteArrayList<AgentWorkbenchService.Scope>();var denied=new AtomicInteger();requests.clear();
            for(var candidate:List.of(service,other))requests.add(racers.submit(()->{admissionGate.await();try{admitted.add(candidate.prepare(alice,"s1","用户确认恢复原任务，不重复写入","recovery-"+UUID.randomUUID()));}catch(org.springframework.web.server.ResponseStatusException conflict){assertThat(conflict.getStatusCode().value()).isEqualTo(409);denied.incrementAndGet();}return null;}));
            admissionGate.countDown();for(var request:requests)request.get(30,TimeUnit.SECONDS);assertThat(admitted).hasSize(1);assertThat(denied.get()).isEqualTo(1);
            var restored=admitted.get(0);restored.repairState();var calls=new AtomicInteger();var bodies=new AtomicInteger();
            var model=mock(Model.class);when(model.getModelName()).thenReturn("scripted-process-recovery");
            when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{List<Msg> messages=inv.getArgument(0);assertThat(messages.stream().flatMap(message->message.getContentBlocks(ToolResultBlock.class).stream()).filter(result->"durable-effect".equals(result.getId())).flatMap(result->result.getOutput().stream()).filter(TextBlock.class::isInstance).map(TextBlock.class::cast).map(TextBlock::getText).toList()).contains("effect committed");calls.incrementAndGet();return Flux.just(ChatResponse.builder().content(List.of(TextBlock.builder().text("已读取原执行证据并完成恢复，未重复写入").build())).finishReason("stop").build());});
            var toolkit=new Toolkit();toolkit.registerAgentTool(new AgentTool(){public String getName(){return "write_effect";}public String getDescription(){return "test effect must not replay";}public Map<String,Object>getParameters(){return Map.of("type","object","properties",Map.of());}public Mono<ToolResultBlock>callAsync(ToolCallParam input){bodies.incrementAndGet();return Mono.error(new AssertionError("Completed effect was replayed"));}});restored.install(toolkit);
            try(var agent=ReActAgent.builder().name("employee-main").model(model).toolkit(toolkit).middlewares(List.of(restored)).stateStore(restored.stateStore()).defaultSessionId(restored.sdkSession()).enablePendingToolRecovery(false).enableMetaTool(false).enableTaskList(false).build()){
                String result=agent.call(List.of(new UserMessage("用户确认恢复原任务，不重复写入")),RuntimeContext.builder().userId("1").sessionId(restored.sdkSession()).build()).block(Duration.ofSeconds(60)).getTextContent();assertThat(result).contains("未重复写入");restored.finish("COMPLETED",result);
            }finally{restored.release();}
            assertThat(calls.get()).isEqualTo(1);assertThat(bodies.get()).isZero();assertThat(item("EXECUTION").status()).isEqualTo("COMPLETED");
            assertThat(store.jdbc().queryForObject("SELECT payload FROM agent_workbench_item WHERE kind='TOOL'",String.class)).isEqualTo(originalReceipt);
            assertThat(store.require(1,"s1",interrupted.id()).data().get("runId")).isNotEqualTo("crashed-attempt");verify(app,never()).continueSession(any(),anyString(),anyString(),anyString());
        }finally{racers.shutdownNow();other.close();}
    }
}
