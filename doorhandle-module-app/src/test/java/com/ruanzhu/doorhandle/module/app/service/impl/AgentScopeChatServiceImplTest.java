package com.ruanzhu.doorhandle.module.app.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import com.ruanzhu.doorhandle.module.app.dto.chat.*;
import com.ruanzhu.doorhandle.module.app.service.*;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.core.task.SyncTaskExecutor;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.function.Consumer;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class AgentScopeChatServiceImplTest {
    private final ChatSessionService sessions = mock(ChatSessionService.class);
    private final AgentConversationApi api = mock(AgentConversationApi.class);
    private final ObjectProvider<AgentConversationApi> provider = mock(ObjectProvider.class);
    private final RagKnowledgeService knowledge = mock(RagKnowledgeService.class);
    private final Mem0Client memory = mock(Mem0Client.class);
    private final ChatAssistantProperties settings = new ChatAssistantProperties();
    private AgentScopeChatServiceImpl service;
    @BeforeEach void setup() {
        login("ROLE_INSPECTOR"); when(provider.getIfAvailable()).thenReturn(api);
        when(knowledge.retrieveContext(anyString())).thenReturn(""); when(sessions.listMessages("alice", "s1")).thenReturn(List.of());
        service = new AgentScopeChatServiceImpl(sessions, provider, knowledge, memory, new SyncTaskExecutor(), settings, new ObjectMapper());
    }
    @AfterEach void clear() { SecurityContextHolder.clearContext(); }
    private void login(String role) {
        var roles = List.of(new SimpleGrantedAuthority(role));
        SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken(new TenantPrincipal(1L, "alice", "", roles), null, roles));
    }
    private ChatSendMessageRequest request() { var request = new ChatSendMessageRequest(); request.setSessionId("s1"); request.setContent("查询任务"); return request; }
    @Test void persistsMessagesAndPassesServerIdentityAndTextHistoryToAgentScope() {
        var previous = new ChatMessageResponse(); previous.setRole("assistant"); previous.setContent("上次回答"); previous.setMessageType("TEXT");
        var card = new ChatMessageResponse(); card.setRole("assistant"); card.setContent("PRIVATE_CARD_JSON"); card.setMessageType("BUSINESS_CARD");
        when(sessions.listMessages("alice", "s1")).thenReturn(List.of(previous, card));
        when(api.start(any(), anyString(), anyList(), anyString(), any())).thenAnswer(invocation -> {
            assertThat(invocation.getArgument(0, AgentActor.class)).isEqualTo(new AgentActor(1, "alice", AgentActor.Role.INSPECTOR));
            assertThat(invocation.getArgument(2, List.class).toString()).contains("上次回答", "查询任务").doesNotContain("PRIVATE_CARD_JSON");
            Consumer<AgentConversationApi.Event> events = invocation.getArgument(4);
            events.accept(new AgentConversationApi.Event("RUN_STARTED", "employee-main", null, null, 0));
            events.accept(new AgentConversationApi.Event("RUN_FINISHED", "employee-main", null, null, 12));
            return new AgentConversationApi.Run(CompletableFuture.completedFuture("查询完成"), () -> {});
        });
        var saved = new ChatMessageResponse(); saved.setContent("查询完成");
        when(sessions.appendAssistantMessage(any(), eq("s1"), eq("查询完成"), eq("TEXT"), eq("AGENTSCOPE"), isNull())).thenReturn(saved);
        assertThat(service.handleUserMessage("alice", request()).getContent()).isEqualTo("查询完成");
        var order = inOrder(sessions); order.verify(sessions).verifySessionOwner("alice", "s1");
        order.verify(sessions).listMessages("alice", "s1"); order.verify(sessions).appendUserMessage(any(), eq("s1"), eq("查询任务"));
        verify(sessions).saveExecutionTrace(any(), eq("s1"), argThat(trace -> trace.contains("AgentScope") && trace.contains("COMPLETED") && trace.contains("RUN_FINISHED")));
    }
    @Test void unsupportedRoleCannotReachHistoryOrAgentExecution() {
        login("ROLE_USER");
        assertThatThrownBy(() -> service.handleUserMessage("alice", request())).hasMessageContaining("权限");
        verifyNoInteractions(sessions, api, knowledge, memory);
    }
    @Test void persistsCardReferencesWithAnswerButNeverCopiesToolFactsIntoTraceOrMemory() throws Exception {
        var ref=new AgentCards.Reference("TASKS","get_task_detail",List.of("task-1"),null);
        when(api.start(any(),anyString(),anyList(),anyString(),any())).thenReturn(new AgentConversationApi.Run(CompletableFuture.completedFuture("查询完成"),()->{},"run-1",()->List.of(ref)));
        when(sessions.appendAssistantMessage(any(),eq("s1"),anyString(),eq("AGENT_CARDS"),eq("AGENTSCOPE"),isNull())).thenAnswer(inv->{var saved=new ChatMessageResponse();saved.setContent(inv.getArgument(2));saved.setMessageType("AGENT_CARDS");return saved;});
        var answer=service.handleUserMessage("alice",request());
        var envelope=new ObjectMapper().readValue(answer.getContent(),AgentCards.Envelope.class);
        assertThat(envelope.text()).isEqualTo("查询完成");assertThat(envelope.cards()).containsExactly(ref);assertThat(envelope.runId()).isEqualTo("run-1");
        verify(memory).addMemoryAsync(any(),eq("s1"),eq("查询任务"),anyMap());
    }
    @Test void restoredCardMessageOnlyFeedsPlainAnswerBackToModel() throws Exception {
        var message=new ChatMessageResponse();message.setRole("assistant");message.setMessageType("AGENT_CARDS");
        message.setContent(new ObjectMapper().writeValueAsString(new AgentCards.Envelope(1,"先前回答","run-old",List.of(new AgentCards.Reference("TASKS","get_task_detail",List.of("private-task-ref"),null)))));
        when(sessions.listMessages("alice","s1")).thenReturn(List.of(message));
        when(api.start(any(),anyString(),anyList(),anyString(),any())).thenAnswer(inv->{assertThat(inv.getArgument(2,List.class).toString()).contains("先前回答").doesNotContain("private-task-ref","run-old");return new AgentConversationApi.Run(CompletableFuture.completedFuture("新的回答"),()->{});});
        when(sessions.appendAssistantMessage(any(),any(),any(),any(),any(),any())).thenReturn(new ChatMessageResponse());
        service.handleUserMessage("alice",request());
    }
    @Test void unavailableFrameworkNeverFallsBackToALegacyClient() {
        when(provider.getIfAvailable()).thenReturn(null);
        assertThatThrownBy(() -> service.handleUserMessage("alice", request())).hasMessageContaining("尚未启用");
        verifyNoInteractions(sessions, api, knowledge, memory);
    }
    @Test void anotherUsersSessionIsRejectedBeforeAnyDataOrModelAccess() {
        doThrow(new IllegalStateException("owner mismatch")).when(sessions).verifySessionOwner("alice", "s1");
        assertThatThrownBy(() -> service.handleUserMessage("alice", request())).hasMessageContaining("owner mismatch");
        verify(sessions, never()).listMessages(any(), any()); verifyNoInteractions(api, knowledge, memory);
    }
    @Test void modelErrorsAreSanitizedAndDoNotPersistAnAssistantAnswer() {
        when(api.start(any(), anyString(), anyList(), anyString(), any())).thenAnswer(invocation -> {
            Consumer<AgentConversationApi.Event> events = invocation.getArgument(4); events.accept(new AgentConversationApi.Event("RUN_STARTED", "employee-main", null, null, 0));
            return new AgentConversationApi.Run(CompletableFuture.failedFuture(new IllegalStateException("secret credential")), () -> {});
        });
        assertThatThrownBy(() -> service.handleUserMessage("alice", request())).hasMessageNotContaining("secret").hasCause(null);
        verify(sessions, never()).appendAssistantMessage(any(), any(), any(), any(), any(), any());
        verify(sessions).saveExecutionTrace(any(), eq("s1"), argThat(trace -> trace.contains("ERROR") && !trace.contains("secret")));
    }
    @Test void oldConfirmedActionsCannotResumeLegacyExecution() {
        var request = new ChatConfirmActionRequest(); request.setSessionId("s1"); request.setActionId("a1"); request.setConfirmed(true);
        assertThatThrownBy(() -> service.confirmAction("alice", request)).hasMessageContaining("旧版 Agent 动作已停用");
        verifyNoInteractions(api); verify(sessions, never()).transitionPendingAction(any(), any(), any(), any(), any(), any());
    }
    @Test void slashCommandsArePersistedButSkipRagMemorySearchAndMemoryExtraction(){
        var command=request();command.setContent("/skills");
        when(api.start(any(),anyString(),anyList(),eq(""),any())).thenReturn(new AgentConversationApi.Run(CompletableFuture.completedFuture("当前角色没有可用技能"),()->{}));
        when(sessions.appendAssistantMessage(any(),any(),any(),any(),any(),any())).thenReturn(new ChatMessageResponse());
        service.handleUserMessage("alice",command);
        verify(sessions).appendUserMessage(any(),eq("s1"),eq("/skills"));verifyNoInteractions(knowledge,memory);
    }
    @Test void aguiUsesDatabaseHistoryAndSameAccountMemoryAndPersistsBeforeReply()throws Exception{
        var previous=new ChatMessageResponse();previous.setRole("assistant");previous.setMessageType("TEXT");previous.setContent("来自主站的历史");
        when(sessions.listMessages("alice","s1")).thenReturn(List.of(previous));
        when(knowledge.retrieveContext("当前问题")).thenReturn("业务参考");
        when(memory.searchAccountMemories(any(),eq("s1"),eq("当前问题"),eq(5))).thenReturn(List.of(java.util.Map.of("memory","本人偏好")));
        when(memory.formatMemoriesAsContext(anyList())).thenReturn("本人偏好");
        when(api.start(any(),eq("s1"),anyList(),anyString(),any(),eq("AGUI"),eq("request-1"))).thenAnswer(inv->{
            assertThat(inv.getArgument(2,List.class).toString()).contains("来自主站的历史","当前问题");assertThat(inv.getArgument(3,String.class)).contains("业务参考","本人偏好");
            return new AgentConversationApi.Run(CompletableFuture.completedFuture("统一回答"),()->{},"durable-1");
        });
        var saved=new ChatMessageResponse();saved.setContent("统一回答");saved.setMessageType("TEXT");
        when(sessions.appendAssistantMessage(any(),eq("s1"),eq("统一回答"),eq("TEXT"),eq("AGENTSCOPE"),isNull())).thenReturn(saved);
        var run=service.start(new AgentActor(1,"alice",AgentActor.Role.INSPECTOR),"s1","request-1","当前问题",event->{});
        assertThat(run.result().get().text()).isEqualTo("统一回答");verify(sessions).appendUserMessage(any(),eq("s1"),eq("当前问题"));verify(sessions).appendAssistantMessage(any(),eq("s1"),eq("统一回答"),eq("TEXT"),eq("AGENTSCOPE"),isNull());
        verify(memory).addMemoryAsync(any(),eq("s1"),eq("当前问题"),anyMap());
    }
    @Test void personalMemoryKeepsUserPreferenceWithoutAssistantClaimsOrRetrievedFacts(){
        var input=request();input.setContent("请记住我的验收资料默认导出为 PDF");
        when(knowledge.retrieveContext(input.getContent())).thenReturn("服务器参考：该用户默认使用 XLSX");
        when(api.start(any(),anyString(),anyList(),anyString(),any())).thenReturn(
                new AgentConversationApi.Run(CompletableFuture.completedFuture("我无法保存偏好；你可以改用 CSV"),()->{}));
        when(sessions.appendAssistantMessage(any(),any(),any(),any(),any(),any())).thenAnswer(inv->{
            var saved=new ChatMessageResponse();saved.setContent(inv.getArgument(2));saved.setId(42L);return saved;
        });
        assertThat(service.handleUserMessage("alice",input).getContent()).contains("无法保存", "CSV");
        verify(memory).addMemoryAsync(any(),eq("s1"),eq(input.getContent()),argThat(metadata->
                metadata.get("turn_id").equals(42L)&&metadata.get("source").equals("agentscope-chat")));
        verify(sessions).appendAssistantMessage(any(),eq("s1"),contains("CSV"),eq("TEXT"),eq("AGENTSCOPE"),isNull());
    }
    @Test void longKnowledgeReferenceCannotTruncateTheAccountPreference(){
        when(knowledge.retrieveContext(anyString())).thenReturn("业务资料".repeat(2000));
        when(memory.searchAccountMemories(any(),eq("s1"),anyString(),eq(5))).thenReturn(List.of(java.util.Map.of("memory","本人时区为 UTC+8")));
        when(memory.formatMemoriesAsContext(anyList())).thenReturn("[用户历史记忆]\n- 本人时区为 UTC+8");
        when(api.start(any(),anyString(),anyList(),anyString(),any())).thenAnswer(inv->{
            String reference=inv.getArgument(3);
            assertThat(reference).hasSize(6000).contains("业务资料").endsWith("[用户历史记忆]\n- 本人时区为 UTC+8");
            return new AgentConversationApi.Run(CompletableFuture.completedFuture("历史记录为 UTC+8"),()->{});
        });
        when(sessions.appendAssistantMessage(any(),any(),any(),any(),any(),any())).thenReturn(new ChatMessageResponse());
        service.handleUserMessage("alice",request());
    }
    @Test void replayRejectedByExecutionDoesNotAppendAnotherUserMessage(){
        when(api.start(any(),anyString(),anyList(),anyString(),any())).thenThrow(new IllegalStateException("duplicate run"));
        assertThatThrownBy(()->service.handleUserMessage("alice",request())).hasMessageContaining("duplicate");
        verify(sessions,never()).appendUserMessage(any(),any(),any());verify(sessions,never()).appendAssistantMessage(any(),any(),any(),any(),any(),any());
    }
    @Test void mismatchedGatewayActorCannotReadSessions(){
        assertThatThrownBy(()->service.start(new AgentActor(2,"alice",AgentActor.Role.INSPECTOR),"s1","r1","问题",e->{})).isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
        verifyNoInteractions(sessions,api,knowledge,memory);
    }
    @Test void bothEntrypointsShareTurnLockAndCancellationReleasesIt()throws Exception{
        var executor=java.util.concurrent.Executors.newSingleThreadExecutor();
        try{
            service=new AgentScopeChatServiceImpl(sessions,provider,knowledge,memory,new org.springframework.scheduling.concurrent.ConcurrentTaskExecutor(executor),settings,new ObjectMapper());
            var pending=new CompletableFuture<String>();var started=new java.util.concurrent.CountDownLatch(1);
            when(api.start(any(),eq("s1"),anyList(),anyString(),any(),eq("AGUI"),eq("first"))).thenAnswer(inv->{started.countDown();return new AgentConversationApi.Run(pending,()->pending.cancel(true),"first-run");});
            var actor=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);var first=service.start(actor,"s1","first","等待回答",e->{});
            assertThat(started.await(5,java.util.concurrent.TimeUnit.SECONDS)).isTrue();
            assertThatThrownBy(()->service.handleUserMessage("alice",request())).hasMessageContaining("上一轮");
            verify(api,never()).start(any(),anyString(),anyList(),anyString(),any());
            first.cancel().run();executor.submit(()->{}).get(5,java.util.concurrent.TimeUnit.SECONDS);
            assertThat(first.result().isCancelled()).isTrue();assertThat(pending.isCancelled()).isTrue();verify(sessions,never()).appendAssistantMessage(any(),any(),any(),any(),any(),any());
            var saved=new ChatMessageResponse();saved.setContent("再次回答");saved.setMessageType("TEXT");
            when(sessions.appendAssistantMessage(any(),any(),any(),any(),any(),any())).thenReturn(saved);
            when(api.start(any(),eq("s1"),anyList(),anyString(),any(),eq("AGUI"),eq("second"))).thenReturn(new AgentConversationApi.Run(CompletableFuture.completedFuture("再次回答"),()->{}));
            assertThat(service.start(actor,"s1","second","重新提问",e->{}).result().get(5,java.util.concurrent.TimeUnit.SECONDS).text()).isEqualTo("再次回答");
        }finally{executor.shutdownNow();}
    }
}
