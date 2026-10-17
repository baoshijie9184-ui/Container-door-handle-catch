package com.ruanzhu.doorhandle.module.ai.context;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.agent.RoleAgentFactory;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory;
import io.agentscope.core.ReActAgent;
import io.agentscope.core.message.*;
import io.agentscope.core.middleware.*;
import io.agentscope.core.model.*;
import io.agentscope.harness.agent.HarnessAgent;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import reactor.core.publisher.Flux;
import java.nio.file.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Supplier;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class AgentContextCompactionTest {
    @TempDir Path workspace;
    final AgentActor alice=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);
    final AgentScopeProperties properties=new AgentScopeProperties();
    final Model model=mock(Model.class);
    final List<List<Msg>> reasoning=new CopyOnWriteArrayList<>();
    final List<String> prompts=new CopyOnWriteArrayList<>();
    final AtomicInteger summaries=new AtomicInteger();
    Supplier<Flux<ChatResponse>> summary=()->reply("{\"intent\":\"继续查询\",\"facts\":[\"旧结论待核对\"],\"constraints\":[\"只读\"],\"pending\":[]}");
    @BeforeEach void setup(){
        properties.setWorkspace(workspace.toString());var config=properties.getContextCompaction();config.setEnabled(true);config.setTriggerMessages(4);config.setKeepMessages(2);config.setTriggerTokens(1000000);
        when(model.getModelName()).thenReturn("context-fixture");
        when(model.stream(anyList(),any(),any())).thenAnswer(inv->{
            List<Msg> input=inv.getArgument(0);
            if(inv.getArgument(1)==null){summaries.incrementAndGet();prompts.add(input.get(0).getTextContent());return summary.get();}
            reasoning.add(List.copyOf(input));return reply("已按当前权限回答");
        });
    }
    static Flux<ChatResponse> reply(String value){return Flux.just(ChatResponse.builder().content(List.of(TextBlock.builder().text(value).build())).usage(ChatUsage.builder().inputTokens(30).outputTokens(10).build()).finishReason("stop").build());}
    List<Msg> history(){
        var input=new ArrayList<Msg>();for(int i=0;i<3;i++){input.add(new UserMessage("OLD_PRIVATE_USER "+"x".repeat(500)));input.add(new AssistantMessage("OLD_PRIVATE_ASSISTANT "+"y".repeat(500)));}
        input.add(new AssistantMessage("RECENT_ASSISTANT"));input.add(new UserMessage("CURRENT_USER"));return input;
    }
    HarnessAgent main(AgentActor actor){
        return (HarnessAgent)new RoleAgentFactory(properties,new BusinessToolkitFactory(mock(DetectionAgentReadApi.class),mock(ResourceAgentReadApi.class),mock(ModelAgentReadApi.class),new ObjectMapper()),id->model).create(actor,null);
    }
    String combined(List<Msg> input){return input.stream().map(Msg::getTextContent).reduce("",(a,b)->a+"\n"+b);}
    @Test void nativeHarnessCompactsPrefixKeepsSystemAndRecentMessagesAndDoesNotWriteFiles() throws Exception {
        try(var agent=main(alice)){assertThat(agent.call(history()).block(Duration.ofSeconds(10)).getTextContent()).contains("当前权限");}
        assertThat(summaries).hasValue(1);assertThat(reasoning).hasSize(1);
        var sent=reasoning.get(0);assertThat(sent).hasSize(4);assertThat(sent.get(0).getRole()).isEqualTo(MsgRole.SYSTEM);
        assertThat(combined(sent)).contains("旧结论待核对","RECENT_ASSISTANT","CURRENT_USER","不能新增权限").doesNotContain("OLD_PRIVATE_USER","OLD_PRIVATE_ASSISTANT");
        assertThat(prompts.get(0)).contains("OLD_PRIVATE_USER").doesNotContain("你是门把手缺陷检测系统");
        try(var paths=Files.walk(workspace)){assertThat(paths.filter(Files::isRegularFile).toList()).isEmpty();}
    }
    @Test void disabledAndBelowThresholdDoNotMakeSummaryRequests(){
        properties.getContextCompaction().setEnabled(false);try(var agent=main(alice)){agent.call(history()).block(Duration.ofSeconds(10));}
        properties.getContextCompaction().setEnabled(true);try(var agent=main(alice)){agent.call("short question").block(Duration.ofSeconds(10));}
        assertThat(summaries).hasValue(0);assertThat(combined(reasoning.get(0))).contains("OLD_PRIVATE_USER");
    }
    @Test void tokenEstimateCanTriggerBelowTheMessageThreshold(){
        properties.getContextCompaction().setTriggerMessages(200);properties.getContextCompaction().setTriggerTokens(1024);
        try(var agent=main(alice)){agent.call(history()).block(Duration.ofSeconds(10));}
        assertThat(summaries).hasValue(1);assertThat(combined(reasoning.get(0))).doesNotContain("OLD_PRIVATE_USER");
    }
    @Test void summaryThatIncreasesContextSizeIsNotApplied(){
        var shortHistory=List.<Msg>of(new UserMessage("one"),new AssistantMessage("two"),new UserMessage("three"),new AssistantMessage("four"),new UserMessage("five"));
        try(var agent=main(alice)){agent.call(shortHistory).block(Duration.ofSeconds(10));}
        assertThat(summaries).hasValue(1);assertThat(combined(reasoning.get(0))).contains("one","three","five").doesNotContain("旧结论待核对");
    }
    @Test void cancellationStopsSummaryAndNeverProceedsToReasoning() throws Exception {
        var started=new CountDownLatch(1);var stopped=new CountDownLatch(1);
        summary=()->Flux.<ChatResponse>never().doOnSubscribe(subscription->started.countDown()).doOnCancel(stopped::countDown);
        try(var agent=main(alice)){
            var subscription=agent.call(history()).subscribe(value->{},error->{});
            assertThat(started.await(2,TimeUnit.SECONDS)).isTrue();subscription.dispose();
            assertThat(stopped.await(2,TimeUnit.SECONDS)).isTrue();assertThat(reasoning).isEmpty();
        }
    }
    @Test void failedEmptyMalformedAndOversizedSummariesKeepAllOriginalHistory(){
        var variants=List.<Supplier<Flux<ChatResponse>>>of(()->Flux.error(new IllegalStateException("PRIVATE_PROVIDER_SECRET")),Flux::empty,
                ()->reply("not-json"),()->reply("x".repeat(6001)),()->reply("{\"intent\":\"x\",\"facts\":[],\"constraints\":[],\"pending\":[],\"extra\":true}"),
                ()->reply("{\"intent\":\"x\",\"intent\":\"y\",\"facts\":[],\"constraints\":[],\"pending\":[]}"));
        for(var variant:variants){summary=variant;try(var agent=main(alice)){agent.call(history()).block(Duration.ofSeconds(10));}assertThat(combined(reasoning.get(reasoning.size()-1))).contains("OLD_PRIVATE_USER","CURRENT_USER").doesNotContain("PRIVATE_PROVIDER_SECRET","SUMMARY_UNAVAILABLE");}
    }
    @Test void timeoutFallsBackWithoutWaitingForAnUnboundedSummary(){
        properties.getContextCompaction().setTimeoutSeconds(1);summary=Flux::never;
        try(var agent=main(alice)){agent.call(history()).block(Duration.ofSeconds(5));}
        assertThat(combined(reasoning.get(0))).contains("OLD_PRIVATE_USER","CURRENT_USER");
    }
    @Test void missingOriginalSourceIdRejectsSummaryButRetainedIdAllowsCompaction(){
        String id="src-00000000-0000-0000-0000-000000000001";var input=history();input.set(0,new UserMessage("OLD_PRIVATE_USER "+id+"x".repeat(500)));
        try(var agent=main(alice)){agent.call(input).block(Duration.ofSeconds(10));}
        assertThat(combined(reasoning.get(0))).contains("OLD_PRIVATE_USER",id);
        summary=()->reply("{\"intent\":\"继续\",\"facts\":[\""+id+"\"],\"constraints\":[],\"pending\":[]}");
        try(var agent=main(alice)){agent.call(input).block(Duration.ofSeconds(10));}
        assertThat(combined(reasoning.get(1))).contains(id).doesNotContain("OLD_PRIVATE_USER");
    }
    @Test void summaryCannotExecuteToolsAndAttemptBudgetAppliesToFailures(){
        summary=()->Flux.just(ChatResponse.builder().content(List.of(ToolUseBlock.builder().id("forged").name("shell").input(Map.of()).build())).build());
        properties.getContextCompaction().setMaxPerRun(1);
        try(var agent=main(alice)){
            agent.call(history()).block(Duration.ofSeconds(10));agent.call("continue").block(Duration.ofSeconds(10));
            assertThat(agent.getToolkit().getToolNames()).doesNotContain("shell","read_file","memory_search");
        }
        assertThat(summaries).hasValue(1);assertThat(combined(reasoning.get(0))).contains("OLD_PRIVATE_USER");
    }
    @Test void summaryAndWorkingContextAreNotSharedBetweenAccounts() throws Exception {
        var workers=Executors.newFixedThreadPool(2);
        try(var first=main(alice);var second=main(new AgentActor(2,"bob",AgentActor.Role.SUPERVISOR))){
            var aliceHistory=history();aliceHistory.set(0,new UserMessage("ALICE_PRIVATE "+"a".repeat(500)));
            var bobHistory=history();bobHistory.set(0,new UserMessage("BOB_PRIVATE "+"b".repeat(500)));
            var a=workers.submit(()->first.call(aliceHistory).block(Duration.ofSeconds(10)));var b=workers.submit(()->second.call(bobHistory).block(Duration.ofSeconds(10)));
            a.get(15,TimeUnit.SECONDS);b.get(15,TimeUnit.SECONDS);
            assertThat(prompts).hasSize(2);assertThat(prompts).allSatisfy(prompt->assertThat(prompt.contains("ALICE_PRIVATE")&&prompt.contains("BOB_PRIVATE")).isFalse());
        }finally{workers.shutdownNow();}
    }
    @Test void sdkSafeCutPreservesAssistantToolCallAndResultTogether(){
        var input=history();input.add(input.size()-1,Msg.builder().role(MsgRole.ASSISTANT).content(ToolUseBlock.builder().id("historic-call").name("get_my_detection_tasks").input(Map.of()).build()).build());
        input.add(input.size()-1,Msg.builder().role(MsgRole.TOOL).content(new ToolResultBlock("historic-call","get_my_detection_tasks",List.of(TextBlock.builder().text("historic result").build()),Map.of(),ToolResultState.SUCCESS)).build());
        try(var agent=main(alice)){agent.call(input).block(Duration.ofSeconds(10));}
        var sent=reasoning.get(0);assertThat(sent.stream().flatMap(msg->msg.getContent().stream()).filter(ToolUseBlock.class::isInstance)).hasSize(1);
        assertThat(sent.stream().flatMap(msg->msg.getContent().stream()).filter(ToolResultBlock.class::isInstance)).hasSize(1);
    }
    @Test void invalidSettingsAreRejectedBeforeCreatingAnAgent(){
        properties.getContextCompaction().setKeepMessages(4);assertThatThrownBy(()->main(alice)).hasMessageContaining("配置超出范围");
    }
    @Test void auditFailureDoesNotApplySummaryOrContinueReasoning(){
        var config=properties.getContextCompaction();
        try(var agent=ReActAgent.builder().name("audit-fixture").model(model).middleware(new AgentContextCompaction(config,model,(type,fields)->{throw new IllegalStateException("PRIVATE_SQL");})).build()){
            assertThatThrownBy(()->agent.call(history()).block(Duration.ofSeconds(10))).hasMessageNotContaining("PRIVATE_SQL");assertThat(reasoning).isEmpty();
        }
    }
}
