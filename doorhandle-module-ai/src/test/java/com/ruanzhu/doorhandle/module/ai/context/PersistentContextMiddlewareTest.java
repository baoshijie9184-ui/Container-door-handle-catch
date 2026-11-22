package com.ruanzhu.doorhandle.module.ai.context;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.agent.AgentContextDataApi;
import com.ruanzhu.doorhandle.contracts.agent.AgentContextDataApi.History;
import com.ruanzhu.doorhandle.contracts.agent.AgentContextDataApi.Message;
import com.ruanzhu.doorhandle.contracts.agent.AgentContextDataApi.Source;
import com.ruanzhu.doorhandle.module.ai.workbench.AgentWorkbenchService;
import io.agentscope.core.ReActAgent;
import io.agentscope.core.message.Msg;
import io.agentscope.core.message.UserMessage;
import io.agentscope.core.model.Model;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;

import static com.ruanzhu.doorhandle.contracts.agent.AgentContextDataApi.RETRIEVAL_POLICY_V2;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.http.HttpStatus.CONFLICT;
import static org.mockito.Mockito.*;

class PersistentContextMiddlewareTest {
    private final AgentActor actor = new AgentActor(1, "inspector", AgentActor.Role.INSPECTOR);
    private final AgentWorkbenchService.Scope scope = mock(AgentWorkbenchService.Scope.class);
    private final DurableContextStore store = mock(DurableContextStore.class);
    private final AgentContextDataApi data = mock(AgentContextDataApi.class);
    private final Model model = mock(Model.class);
    private final ContextCompactionSettings settings = new ContextCompactionSettings();
    private final List<Msg> current = List.of(new UserMessage("查看目前可以读取的检测记录"));

    @BeforeEach void bindScope() {
        when(scope.contextActor()).thenReturn(actor);
        when(scope.contextSession()).thenReturn("session");
        when(scope.contextTask()).thenReturn("task");
        when(scope.contextKey()).thenReturn("main");
        when(scope.runId()).thenReturn("run");
        when(scope.initialContextMessages()).thenReturn(current);
    }

    @Test void authorizesRecentHistoryWithoutCallingTheCompactor() {
        var allowed = new Source("TASK", "allowed", "");
        var revoked = new Source("MEMORY", "revoked", "0:" + "a".repeat(64));
        var currentKnowledge = new Source("KNOWLEDGE", "doc-1", "2:3:" + "b".repeat(64));
        when(scope.initialContextSources()).thenReturn(List.of(currentKnowledge));
        when(store.bootstrap(actor, "session", "main", "task", current))
                .thenReturn(new DurableContextStore.Bootstrap(16, current, false));
        when(store.data()).thenReturn(data);
        when(data.recentHistory(actor, "session", 16, 38)).thenReturn(new History(16, List.of(
                new Message(12, "user", "我的历史问题", List.of()),
                new Message(13, "assistant", "缺少来源的原始回答", List.of()),
                new Message(14, "assistant", "可查阅的检测结果", List.of()),
                new Message(15, "assistant", "已撤销授权的原始结果", List.of()),
                new Message(16, "assistant", "已有旧来源但可能使用旧检索", List.of())), true));
        when(store.turnSources(actor, "session", 13)).thenReturn(null);
        when(store.turnSources(actor, "session", 14)).thenReturn(List.of(allowed,RETRIEVAL_POLICY_V2));
        when(store.turnSources(actor, "session", 15)).thenReturn(List.of(revoked,RETRIEVAL_POLICY_V2));
        when(store.turnSources(actor, "session", 16)).thenReturn(List.of(allowed));
        when(store.authorized(eq(actor), eq("session"), anyList())).thenAnswer(call ->
                !call.<List<Source>>getArgument(2).contains(revoked));
        doAnswer(call -> { call.<Runnable>getArgument(4).run(); return null; })
                .when(store).initialized(eq(actor), eq("session"), eq("main"), eq("task"), any(Runnable.class));

        settings.setTriggerMessages(4);
        settings.setKeepMessages(2);
        var sent = new AtomicReference<List<Msg>>();
        when(model.getModelName()).thenReturn("model-fixture");
        when(model.stream(anyList(), any(), any())).thenAnswer(call -> {
            sent.set(List.copyOf(call.getArgument(0)));
            return AgentContextCompactionTest.reply("已按当前权限回答");
        });

        var middleware = new PersistentContextMiddleware(store, scope, settings, model, (type, fields) -> {});
        try (var agent = ReActAgent.builder().name("context-fixture").model(model)
                .sysPrompt("检查历史权限").middleware(middleware).build()) {
            assertThat(agent.call(current).block(Duration.ofSeconds(5)).getTextContent()).isEqualTo("已按当前权限回答");
        }

        assertThat(sent.get()).extracting(Msg::getTextContent)
                .containsSubsequence("我的历史问题",
                        "[此段旧回答没有可验证的工具和检索来源记录；原文保留在聊天记录，关键业务事实请重新查询]",
                        "可查阅的检测结果", "[历史资料授权已变化，此段不作为本轮上下文依据]", current.get(0).getTextContent())
                .doesNotContain("缺少来源的原始回答", "已撤销授权的原始结果", "已有旧来源但可能使用旧检索");
        verify(data).recentHistory(actor, "session", 16, 38);
        verify(store).recordSeed(actor, "session", "main", "task", "run", List.of(currentKnowledge, RETRIEVAL_POLICY_V2, allowed));
        verify(store, never()).load(any(), anyString(), anyString());
        verify(model).stream(anyList(), any(), any());
    }

    @Test void revalidatesFreshReferenceBeforeStoringOrUsingItsText() {
        var revoked = new Source("KNOWLEDGE", "doc-1", "2:3:" + "a".repeat(64));
        when(scope.initialContextSources()).thenReturn(List.of(revoked));
        when(store.authorized(actor, "session", List.of(revoked))).thenReturn(false);

        assertThatThrownBy(() -> new PersistentContextMiddleware(store, scope, settings, model, (type, fields) -> {}))
                .isInstanceOf(ResponseStatusException.class).hasMessageContaining("参考资料的权限或版本已变化");
        verify(store, never()).bootstrap(any(), anyString(), anyString(), anyString(), anyList());
        verifyNoInteractions(model, data);
    }

    @Test void rejectsOldCheckpointBeforeCreatingABootstrapOrCallingTheModel() {
        when(scope.restoringContext()).thenReturn(true);
        doThrow(new ResponseStatusException(CONFLICT, "旧检查点缺少可验证的上下文来源"))
                .when(store).assertCheckpointReadable(actor, "session", "main", "task");

        assertThatThrownBy(() -> new PersistentContextMiddleware(store, scope, settings, model, (type, fields) -> {}))
                .isInstanceOf(ResponseStatusException.class).hasMessageContaining("旧检查点缺少可验证的上下文来源");
        verify(store, never()).bootstrap(any(), anyString(), anyString(), anyString(), anyList());
        verifyNoInteractions(model, data);
    }
}
