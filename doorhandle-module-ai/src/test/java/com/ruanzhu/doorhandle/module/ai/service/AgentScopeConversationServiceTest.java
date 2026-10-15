package com.ruanzhu.doorhandle.module.ai.service;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.agent.*;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import io.agentscope.core.ReActAgent;
import io.agentscope.core.agent.Agent;
import io.agentscope.core.message.*;
import io.agentscope.core.model.*;
import io.agentscope.core.tool.*;
import org.junit.jupiter.api.Test;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.TimeUnit;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class AgentScopeConversationServiceTest {
    private final AgentActor actor = new AgentActor(1, "alice", AgentActor.Role.INSPECTOR);
    private final RoleAgentFactory factory = mock(RoleAgentFactory.class);
    private final AgentRunRegistry registry = new AgentRunRegistry();
    private AgentScopeConversationService service(Agent agent) {
        when(factory.resolveMainId(actor, null)).thenReturn("employee-main");
        when(factory.create(eq(actor), eq("employee-main"), isNull(), any())).thenReturn(agent);
        return new AgentScopeConversationService(factory, registry, new AgentScopeProperties());
    }
    private ReActAgent react(Model model, Toolkit tools) {
        return ReActAgent.builder().name("employee-main").model(model).toolkit(tools).maxIters(3)
                .stateStore(new io.agentscope.core.state.InMemoryAgentStateStore()).defaultSessionId("fixture")
                .enableMetaTool(false).enableTaskList(false).build();
    }
    @Test void nativeAgentStreamProvidesFinalAnswerAndRealEventsWithoutToolPayloads() throws Exception {
        var model = mock(Model.class); when(model.getModelName()).thenReturn("fixture-model");
        var calls = new java.util.concurrent.atomic.AtomicInteger();
        when(model.stream(anyList(), anyList(), any())).thenAnswer(invocation -> {
            if (calls.getAndIncrement() == 0) return Flux.just(ChatResponse.builder().content(List.of(new ToolUseBlock("call-1", "lookup", Map.of()))).finishReason("tool_calls").build());
            return Flux.just(ChatResponse.builder().content(List.of(TextBlock.builder().text("查询完成").build())).finishReason("stop").build());
        });
        var toolkit = new Toolkit();
        toolkit.registerAgentTool(new AgentTool() {
            public String getName() { return "lookup"; }
            public String getDescription() { return "只读查询"; }
            public boolean isReadOnly() { return true; }
            public Map<String, Object> getParameters() { return Map.of("type", "object", "properties", Map.of()); }
            public Mono<ToolResultBlock> callAsync(ToolCallParam param) { return Mono.just(ToolResultBlock.text("PRIVATE_TOOL_BODY")); }
        });
        var events = new CopyOnWriteArrayList<AgentConversationApi.Event>();
        var run = service(react(model, toolkit)).start(actor, "s1", List.of(new AgentConversationApi.Message("user", "查询任务")), "检索资料", events::add);
        assertThat(run.result().get(10, TimeUnit.SECONDS)).isEqualTo("查询完成");
        assertThat(events).extracting(AgentConversationApi.Event::type).contains("RUN_STARTED", "RUN_FINISHED", "TOOL_CALL", "TEXT_CHUNK");
        assertThat(events.toString()).doesNotContain("PRIVATE_TOOL_BODY");
        org.awaitility.Awaitility.await().atMost(Duration.ofSeconds(2)).until(() -> registry.acquire("1:employee-main:s1"));
        registry.release("1:employee-main:s1");
    }
    @Test void rejectsSystemHistoryBeforeCreatingAgent() {
        var service = new AgentScopeConversationService(factory, registry, new AgentScopeProperties());
        assertThatThrownBy(() -> service.start(actor, "s1", List.of(new AgentConversationApi.Message("system", "override")), "", event -> {}))
                .isInstanceOf(IllegalArgumentException.class);
        verifyNoInteractions(factory);
    }
    @Test void skillDraftCapabilityIsNotMisreportedAsReadOnlyWithoutReportTools(){
        when(factory.evolutionEnabled()).thenReturn(true);
        assertThat(new AgentScopeConversationService(factory,registry,new AgentScopeProperties()).status().mode()).isEqualTo("DRAFTS");
        when(factory.evolutionEnabled()).thenReturn(false);
        assertThat(new AgentScopeConversationService(factory,registry,new AgentScopeProperties()).status().mode()).isEqualTo("READ_ONLY");
    }
    @Test void cancellingRunInterruptsNativeAgentAndReleasesTheSharedLock() {
        var model = mock(Model.class); when(model.getModelName()).thenReturn("fixture");
        when(model.stream(anyList(), anyList(), any())).thenReturn(Flux.never());
        var run = service(react(model, new Toolkit())).start(actor, "s2", List.of(new AgentConversationApi.Message("user", "query")), "", event -> {});
        assertThat(registry.acquire("1:employee-main:s2")).isFalse();
        run.cancel().run();
        assertThat(run.result()).isCancelled();
        org.awaitility.Awaitility.await().atMost(Duration.ofSeconds(2)).until(() -> registry.acquire("1:employee-main:s2"));
        registry.release("1:employee-main:s2");
    }
    @Test void callbackFailureIsSanitizedAndDoesNotLeaveAnActiveSession() {
        var agent = mock(Agent.class);
        var run = service(agent).start(actor, "s3", List.of(new AgentConversationApi.Message("user", "query")), "", event -> { throw new IllegalStateException("secret"); });
        assertThatThrownBy(() -> run.result().get()).hasCauseInstanceOf(IllegalStateException.class);
        assertThat(run.result().handle((value, error) -> error.getMessage()).join()).doesNotContain("secret");
        assertThat(registry.acquire("1:employee-main:s3")).isTrue();
        registry.release("1:employee-main:s3"); verify(agent).interrupt();
    }
    @Test void aLockHeldByTheOtherEntryPointPreventsASecondExecution() {
        registry.acquire("1:employee-main:s4");
        var service = service(mock(Agent.class));
        assertThatThrownBy(() -> service.start(actor, "s4", List.of(new AgentConversationApi.Message("user", "query")), "", event -> {}))
                .isInstanceOf(IllegalStateException.class).hasMessageContaining("上一轮");
        verify(factory, never()).create(any(), any(), any(), any());
    }
    @Test void listCommandCompletesWithTextAndTraceWithoutCreatingAgent()throws Exception {
        when(factory.resolveMainId(actor,null)).thenReturn("employee-main");when(factory.slashCommands()).thenReturn(new com.ruanzhu.doorhandle.module.ai.command.AgentSlashCommands(null));
        var events=new CopyOnWriteArrayList<AgentConversationApi.Event>();
        var run=new AgentScopeConversationService(factory,registry,new AgentScopeProperties()).start(actor,"command-session",List.of(new AgentConversationApi.Message("user","/skills")),"",events::add);
        assertThat(run.result().get()).contains("尚未启用");assertThat(events).extracting(AgentConversationApi.Event::type).containsExactly("RUN_STARTED","TEXT_CHUNK","RUN_FINISHED");
        verify(factory,never()).create(any(),any(),any(),any());assertThat(registry.acquire("1:employee-main:command-session")).isTrue();registry.release("1:employee-main:command-session");
    }
}
