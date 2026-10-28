package com.ruanzhu.doorhandle.module.app.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatSessionResponse;
import com.ruanzhu.doorhandle.module.app.entity.ChatMessage;
import com.ruanzhu.doorhandle.module.app.entity.ChatPendingAction;
import com.ruanzhu.doorhandle.module.app.entity.ChatSession;
import com.ruanzhu.doorhandle.module.app.mapper.ChatMessageMapper;
import com.ruanzhu.doorhandle.module.app.mapper.ChatPendingActionMapper;
import com.ruanzhu.doorhandle.module.app.mapper.ChatSessionMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.Collections;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ChatSessionServiceImplTest {

    @Test void historyHydratesExecutionLinksOnlyAfterOwnershipIsVerified(){
        var session=new ChatSession();session.setSessionId("s-owned");session.setUserId(1L);session.setUsername("alice");
        when(chatSessionMapper.selectOne(any())).thenReturn(session);
        var stored=new ChatMessage();stored.setId(31L);stored.setSessionId("s-owned");stored.setRole("assistant");stored.setMessageType("TEXT");stored.setContent("历史正文");
        when(chatMessageMapper.findBySessionId("s-owned")).thenReturn(List.of(stored));
        var links=mock(MessageExecutionLinks.class);
        org.springframework.beans.factory.ObjectProvider<MessageExecutionLinks> provider=mock(org.springframework.beans.factory.ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(links);chatSessionService.setExecutionLinks(provider);
        org.mockito.Mockito.doAnswer(inv->{List<com.ruanzhu.doorhandle.module.app.dto.chat.ChatMessageResponse> page=inv.getArgument(2);page.get(0).setRunId("exact-run");return null;})
                .when(links).hydrate(any(),org.mockito.ArgumentMatchers.eq("s-owned"),any());
        var page=chatSessionService.listMessages("alice","s-owned");
        assertThat(page).singleElement().satisfies(message->{assertThat(message.getRunId()).isEqualTo("exact-run");assertThat(message.getContent()).isEqualTo("历史正文");});
        var order=org.mockito.Mockito.inOrder(chatSessionMapper,chatMessageMapper,links);
        order.verify(chatSessionMapper).selectOne(any());order.verify(chatMessageMapper).findBySessionId("s-owned");
        order.verify(links).hydrate(org.mockito.ArgumentMatchers.eq(new TenantContext(1L,"alice")),org.mockito.ArgumentMatchers.eq("s-owned"),any());
        org.mockito.Mockito.clearInvocations(links,chatMessageMapper);when(chatSessionMapper.selectOne(any())).thenReturn(null);
        assertThatThrownBy(()->chatSessionService.listMessages("bob","s-owned")).isInstanceOf(BusinessException.class);
        org.mockito.Mockito.verifyNoInteractions(links,chatMessageMapper);
    }

    @BeforeAll
    static void initMetadata() {
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), ""), ChatSession.class);
    }

    private ChatSessionMapper chatSessionMapper;
    private ChatMessageMapper chatMessageMapper;
    private ChatPendingActionMapper pendingActionMapper;
    private ChatSessionServiceImpl chatSessionService;

    @BeforeEach
    void setUp() {
        chatSessionMapper = mock(ChatSessionMapper.class);
        chatMessageMapper = mock(ChatMessageMapper.class);
        pendingActionMapper = mock(ChatPendingActionMapper.class);

        ChatAssistantProperties properties = new ChatAssistantProperties();
        properties.setDefaultSessionSuffix("default");
        properties.setMaxHistoryMessages(30);

        chatSessionService = new ChatSessionServiceImpl(
                chatSessionMapper,
                chatMessageMapper,
                pendingActionMapper,
                properties,
                new ObjectMapper()
        );
    }

    @Test
    void traceReadsSdkEventsButDoesNotPresentLegacyGraphStateAsATrace() {
        ChatSession session = new ChatSession();
        session.setSessionId("session-1");
        session.setStateJson("{\"framework\":\"AgentScope\",\"runId\":\"run-1\",\"status\":\"COMPLETED\",\"events\":[{\"type\":\"TOOL_CALL\",\"agent\":\"employee-main\",\"tool\":\"delegate_detection_task\",\"elapsedMs\":17}]}");
        when(chatSessionMapper.selectOne(any())).thenReturn(session);
        var trace = chatSessionService.getExecutionTrace("alice", "session-1");
        assertThat(trace.getSessionId()).isEqualTo("session-1");
        assertThat(trace.getRunId()).isEqualTo("run-1");
        assertThat(trace.getEvents()).singleElement().satisfies(event -> {
            assertThat(event.tool()).isEqualTo("delegate_detection_task");
            assertThat(event.elapsedMs()).isEqualTo(17);
        });
        session.setStateJson("{\"currentNode\":\"router\",\"messages\":[\"private old state\"]}");
        trace = chatSessionService.getExecutionTrace("alice", "session-1");
        assertThat(trace.getRunId()).isNull();
        assertThat(trace.getEvents()).isEmpty();
    }
    @Test void sessionPreviewShowsCardAnswerInsteadOfProtocolOrResourceReferences() throws Exception {
        var session=new ChatSession();session.setSessionId("session-card");session.setUsername("alice");session.setStatus("ACTIVE");
        var message=new ChatMessage();message.setMessageType("AGENT_CARDS");
        message.setContent(new ObjectMapper().writeValueAsString(new com.ruanzhu.doorhandle.contracts.agent.AgentCards.Envelope(1,"本人任务查询完成","run-1",List.of(new com.ruanzhu.doorhandle.contracts.agent.AgentCards.Reference("TASKS","get_task_detail",List.of("private-task-ref"),null)))));
        when(chatSessionMapper.selectList(any())).thenReturn(List.of(session));when(chatMessageMapper.selectList(any())).thenReturn(List.of(message));
        assertThat(chatSessionService.listUserSessions("alice").get(0).getLastMessage()).isEqualTo("本人任务查询完成");
        message.setContent("invalid-card-json");assertThat(chatSessionService.listUserSessions("alice").get(0).getLastMessage()).isEqualTo("助手业务卡片");
    }

    @Test
    void traceAccessAndPersistenceRejectAConversationOutsideTheOwnerScope() {
        when(chatSessionMapper.selectOne(any())).thenReturn(null);
        assertThatThrownBy(() -> chatSessionService.getExecutionTrace("alice", "other-session"))
                .isInstanceOf(BusinessException.class);
        assertThatThrownBy(() -> chatSessionService.saveExecutionTrace(new TenantContext(42L, "alice"), "other-session", "{}"))
                .isInstanceOf(BusinessException.class);
        verify(chatSessionMapper, never()).saveExecutionTrace(any(), any(), any());
    }

    @Test
    void shouldCreateDefaultSessionWhenMissing() {
        when(chatSessionMapper.selectList(any())).thenReturn(Collections.emptyList());
        when(chatSessionMapper.selectOne(any())).thenReturn(null);
        when(chatMessageMapper.findBySessionId(anyString())).thenReturn(Collections.emptyList());

        ChatSessionResponse response = chatSessionService.getOrCreateActiveSession("admin");

        assertThat(response.getSessionId()).startsWith("sess_admin_");
        verify(chatSessionMapper).insert(any(ChatSession.class));
        verify(chatMessageMapper).insert(any(ChatMessage.class));
    }

    @AfterEach
    void clearSecurityContext() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void createdSessionStoresImmutableTenantUserId() {
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(
                        new TenantPrincipal(42L, "alice", "N/A", List.of()), null, List.of()));
        when(chatMessageMapper.findBySessionId(anyString())).thenReturn(Collections.emptyList());
        ArgumentCaptor<ChatSession> captor = ArgumentCaptor.forClass(ChatSession.class);

        chatSessionService.createSession("alice");

        verify(chatSessionMapper).insert(captor.capture());
        assertThat(captor.getValue().getUserId()).isEqualTo(42L);
    }

    @Test
    void sessionListFiltersByImmutableTenantUserId() {
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(
                        new TenantPrincipal(42L, "alice", "N/A", List.of()), null, List.of()));
        ArgumentCaptor<LambdaQueryWrapper<ChatSession>> captor = ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        when(chatSessionMapper.selectList(captor.capture())).thenReturn(Collections.emptyList());

        chatSessionService.listUserSessions("alice");

        assertThat(captor.getValue().getSqlSegment()).contains("user_id").doesNotContain("username");
    }

    @Test
    void activeSessionLookupFiltersByImmutableTenantUserId() {
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(
                        new TenantPrincipal(42L, "alice", "N/A", List.of()), null, List.of()));
        ArgumentCaptor<LambdaQueryWrapper<ChatSession>> captor = ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        ChatSession active = new ChatSession();
        active.setSessionId("sess_alice_001");
        active.setUserId(42L);
        active.setUsername("alice");
        when(chatSessionMapper.selectList(captor.capture())).thenReturn(List.of(active));
        when(chatMessageMapper.findBySessionId(active.getSessionId())).thenReturn(List.of());

        chatSessionService.getOrCreateActiveSession("alice");

        assertThat(captor.getValue().getSqlSegment()).contains("user_id").doesNotContain("username");
    }

    @Test
    void shouldAppendAssistantMessage() {
        ChatSession session = new ChatSession();
        session.setSessionId("sess_admin_default");
        session.setUserId(1L);
        when(chatSessionMapper.selectOne(any())).thenReturn(session);

        ArgumentCaptor<ChatMessage> captor = ArgumentCaptor.forClass(ChatMessage.class);
        chatSessionService.appendAssistantMessage(
                new TenantContext(1L, "admin"), "sess_admin_default", "测试消息", "TEXT", "TEST", null);

        verify(chatMessageMapper).insert(captor.capture());
        assertThat(captor.getValue().getSessionId()).isEqualTo("sess_admin_default");
        assertThat(captor.getValue().getRole()).isEqualTo("assistant");
    }

    @Test
    void shouldRejectMessageWriteWhenSessionDoesNotBelongToTenant() {
        TenantContext tenant = new TenantContext(42L, "alice");
        when(chatSessionMapper.selectOne(any())).thenReturn(null);

        assertThatThrownBy(() -> chatSessionService.appendUserMessage(tenant, "sess_other", "hello"))
                .isInstanceOf(BusinessException.class)
                .hasMessage("会话不存在");
        verify(chatMessageMapper, never()).insert(any(ChatMessage.class));
    }

    @Test
    void shouldRejectSessionAccessWhenOwnerDoesNotMatch() {
        when(chatSessionMapper.selectOne(any())).thenReturn(null);

        assertThatThrownBy(() -> chatSessionService.getSession("other", "sess_admin_default"))
                .isInstanceOf(BusinessException.class)
                .hasMessage("会话不存在");
    }

    @Test
    void shouldLoadMessagesOnlyAfterOwnerVerified() {
        ChatSession session = new ChatSession();
        session.setSessionId("sess_admin_default");
        session.setUsername("admin");
        session.setStatus("ACTIVE");
        when(chatSessionMapper.selectOne(any())).thenReturn(session);
        when(chatMessageMapper.findBySessionId("sess_admin_default")).thenReturn(Collections.emptyList());

        assertThat(chatSessionService.listMessages("admin", "sess_admin_default")).isEmpty();

        verify(chatMessageMapper).findBySessionId("sess_admin_default");
    }

    @Test
    void shouldMarkPendingActionBySessionAndActionId() {
        ChatSession session = new ChatSession();
        session.setSessionId("sess_admin_default");
        session.setUserId(1L);
        when(chatSessionMapper.selectOne(any())).thenReturn(session);
        ChatPendingAction action = new ChatPendingAction();
        action.setSessionId("sess_admin_default");
        action.setActionId("action-1");
        when(pendingActionMapper.selectOne(any())).thenReturn(action);

        chatSessionService.markPendingActionStatus(
                new TenantContext(1L, "admin"), "sess_admin_default", "action-1", "CONFIRMED");

        assertThat(action.getStatus()).isEqualTo("CONFIRMED");
        verify(pendingActionMapper).updateById(action);
    }

    @Test
    void transitionsOnlyFromExpectedPendingStatus() {
        ChatSession session = new ChatSession();
        session.setSessionId("sess_admin_default");
        session.setUserId(1L);
        when(chatSessionMapper.selectOne(any())).thenReturn(session);
        when(pendingActionMapper.transitionStatus(
                "sess_admin_default", "action-1", "PENDING", "EXECUTING", null))
                .thenReturn(1);

        boolean claimed = chatSessionService.transitionPendingAction(
                new TenantContext(1L, "admin"), "sess_admin_default", "action-1",
                "PENDING", "EXECUTING", null);

        assertThat(claimed).isTrue();
    }
}
