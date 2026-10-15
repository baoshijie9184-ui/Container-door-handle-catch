package com.ruanzhu.doorhandle.module.app.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatMessageResponse;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatPendingActionPayload;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatSessionResponse;
import com.ruanzhu.doorhandle.module.app.dto.chat.ConversationTraceResponse;
import com.ruanzhu.doorhandle.module.app.entity.ChatMessage;
import com.ruanzhu.doorhandle.module.app.entity.ChatPendingAction;
import com.ruanzhu.doorhandle.module.app.entity.ChatSession;
import com.ruanzhu.doorhandle.module.app.mapper.ChatMessageMapper;
import com.ruanzhu.doorhandle.module.app.mapper.ChatPendingActionMapper;
import com.ruanzhu.doorhandle.module.app.mapper.ChatSessionMapper;
import com.ruanzhu.doorhandle.module.app.service.ChatSessionService;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class ChatSessionServiceImpl implements ChatSessionService {

    private static final DateTimeFormatter TIME_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final ChatSessionMapper chatSessionMapper;
    private final ChatMessageMapper chatMessageMapper;
    private final ChatPendingActionMapper chatPendingActionMapper;
    private final ChatAssistantProperties chatAssistantProperties;
    private final ObjectMapper objectMapper;

    @Override
    public ChatSessionResponse getOrCreateActiveSession(String username) {
        // 优先查找最近的 ACTIVE 会话
        LambdaQueryWrapper<ChatSession> activeQuery = new LambdaQueryWrapper<>();
        Long userId = currentUserId();
        if (userId != null) activeQuery.eq(ChatSession::getUserId, userId);
        else activeQuery.eq(ChatSession::getUsername, username);
        List<ChatSession> activeSessions = chatSessionMapper.selectList(activeQuery
                .eq(ChatSession::getStatus, "ACTIVE")
                .orderByDesc(ChatSession::getUpdatedAt)
                .last("limit 1"));
        if (activeSessions != null && !activeSessions.isEmpty()) {
            return buildSessionResponse(activeSessions.get(0), true);
        }

        // 检查默认会话是否存在（向后兼容）
        String defaultId = buildDefaultSessionId(username);
        LambdaQueryWrapper<ChatSession> defaultQuery = new LambdaQueryWrapper<ChatSession>()
                .eq(ChatSession::getSessionId, defaultId);
        if (userId != null) defaultQuery.eq(ChatSession::getUserId, userId);
        else defaultQuery.eq(ChatSession::getUsername, username);
        ChatSession defaultSession = chatSessionMapper.selectOne(defaultQuery.last("limit 1"));
        if (defaultSession != null) {
            defaultSession.setStatus("ACTIVE");
            defaultSession.setUpdatedAt(LocalDateTime.now());
            chatSessionMapper.updateById(defaultSession);
            return buildSessionResponse(defaultSession, true);
        }

        // 创建新会话
        return createSessionInternal(username, "智能助手对话");
    }

    @Override
    public List<ChatSessionResponse> listUserSessions(String username) {
        LambdaQueryWrapper<ChatSession> query = new LambdaQueryWrapper<>();
        Long userId = currentUserId();
        if (userId != null) query.eq(ChatSession::getUserId, userId);
        else query.eq(ChatSession::getUsername, username);
        List<ChatSession> sessions = chatSessionMapper.selectList(query
                .eq(ChatSession::getStatus, "ACTIVE")
                .orderByDesc(ChatSession::getPinned)
                .orderByDesc(ChatSession::getUpdatedAt));

        return sessions.stream()
                .map(s -> buildSessionResponse(s, false))
                .collect(Collectors.toList());
    }

    @Override
    public ChatSessionResponse createSession(String username) {
        // 标题将根据第一条消息动态更新
        return createSessionInternal(username, "新对话");
    }

    @Override
    public ChatSessionResponse getSession(String username, String sessionId) {
        ChatSession session = requireOwnedSession(username, sessionId);
        return buildSessionResponse(session, true);
    }

    @Override
    public ConversationTraceResponse getExecutionTrace(String username, String sessionId) {
        ChatSession session = requireOwnedSession(username, sessionId);
        var response = new ConversationTraceResponse();
        String traceJson = session.getStateJson();
        if (StringUtils.hasText(traceJson)) try {
            var tree = objectMapper.readTree(traceJson);
            if ("AgentScope".equals(tree.path("framework").asText())) response = objectMapper.treeToValue(tree, ConversationTraceResponse.class);
        } catch (JsonProcessingException ignored) {
            response.setStatus("UNAVAILABLE");
        }
        response.setSessionId(sessionId);
        return response;
    }

    @Override
    public void archiveSession(String username, String sessionId) {
        ChatSession session = requireOwnedSession(username, sessionId);
        session.setStatus("ARCHIVED");
        session.setUpdatedAt(LocalDateTime.now());
        chatSessionMapper.updateById(session);
    }

    @Override
    public void renameSession(String username, String sessionId, String title) {
        if (!StringUtils.hasText(title)) {
            throw new BusinessException(400, "标题不能为空");
        }
        ChatSession session = requireOwnedSession(username, sessionId);
        session.setTitle(title.trim());
        session.setUpdatedAt(LocalDateTime.now());
        chatSessionMapper.updateById(session);
    }

    @Override
    public void deleteSession(String username, String sessionId) {
        ChatSession session = requireOwnedSession(username, sessionId);
        // 删除关联的消息
        chatMessageMapper.delete(new LambdaQueryWrapper<ChatMessage>()
                .eq(ChatMessage::getSessionId, sessionId));
        // 删除关联的待确认动作
        chatPendingActionMapper.delete(new LambdaQueryWrapper<ChatPendingAction>()
                .eq(ChatPendingAction::getSessionId, sessionId));
        // 删除会话
        chatSessionMapper.deleteById(session.getId());
    }

    @Override
    public void togglePinSession(String username, String sessionId, boolean pinned) {
        ChatSession session = requireOwnedSession(username, sessionId);
        session.setPinned(pinned);
        session.setUpdatedAt(LocalDateTime.now());
        chatSessionMapper.updateById(session);
    }

    // ---- private helpers ----

    private ChatSessionResponse createSessionInternal(String username, String title) {
        String sessionId = "sess_" + username + "_" + UUID.randomUUID().toString().substring(0, 8);
        ChatSession session = new ChatSession();
        session.setSessionId(sessionId);
        session.setUsername(username);
        session.setUserId(currentUserId());
        session.setTitle(title);
        session.setStatus("ACTIVE");
        session.setCreatedAt(LocalDateTime.now());
        session.setUpdatedAt(LocalDateTime.now());
        chatSessionMapper.insert(session);
        saveMessage(sessionId, "assistant", "TEXT", "你好，我是系统智能助手。你可以直接告诉我想做检测、查设备、看报表，或者排查任务失败原因。", "GREETING", null);
        return buildSessionResponse(session, true);
    }

    private ChatSessionResponse buildSessionResponse(ChatSession session, boolean includeMessages) {
        ChatSessionResponse response = new ChatSessionResponse();
        response.setSessionId(session.getSessionId());
        response.setTitle(session.getTitle());
        response.setStatus(session.getStatus());
        response.setPinned(session.getPinned() != null && session.getPinned());
        response.setProjectId(session.getProjectId());
        response.setUpdatedAt(session.getUpdatedAt() == null ? null : session.getUpdatedAt().format(TIME_FORMATTER));

        // 统计消息数
        Long count = chatMessageMapper.selectCount(new LambdaQueryWrapper<ChatMessage>()
                .eq(ChatMessage::getSessionId, session.getSessionId()));
        response.setMessageCount(count != null ? count.intValue() : 0);

        // 最后一条消息预览
        List<ChatMessage> lastMsg = chatMessageMapper.selectList(new LambdaQueryWrapper<ChatMessage>()
                .eq(ChatMessage::getSessionId, session.getSessionId())
                .orderByDesc(ChatMessage::getId)
                .last("limit 1"));
        if (lastMsg != null && !lastMsg.isEmpty()) {
            String content = lastMsg.get(0).getContent();
            if (com.ruanzhu.doorhandle.contracts.agent.AgentCards.MESSAGE_TYPE.equals(lastMsg.get(0).getMessageType())) {
                try { content=objectMapper.readValue(content,com.ruanzhu.doorhandle.contracts.agent.AgentCards.Envelope.class).text(); }
                catch(Exception ignored) {content="助手业务卡片";}
            }
            response.setLastMessage(content != null && content.length() > 30 ? content.substring(0, 30) + "…" : content);
        }

        if (includeMessages) {
            response.setMessages(listMessagesInternal(session.getSessionId()));
        }
        return response;
    }

    @Override
    public ChatMessageResponse appendUserMessage(TenantContext tenant, String sessionId, String content) {
        requireOwnedSession(tenant, sessionId);
        return saveMessage(sessionId, "user", "TEXT", content, null, null);
    }

    @Override
    public ChatMessageResponse appendAssistantMessage(TenantContext tenant, String sessionId, String content,
                                                       String messageType, String intent, String actionId) {
        requireOwnedSession(tenant, sessionId);
        return saveMessage(sessionId, "assistant", messageType, content, intent, actionId);
    }

    @Override
    public List<ChatMessageResponse> listMessages(String username, String sessionId) {
        requireOwnedSession(username, sessionId);
        return listMessagesInternal(sessionId);
    }

    private List<ChatMessageResponse> listMessagesInternal(String sessionId) {
        List<ChatMessage> messages = chatMessageMapper.findBySessionId(sessionId);
        return messages.stream()
                .sorted(Comparator.comparing(ChatMessage::getId))
                .skip(Math.max(0, messages.size() - chatAssistantProperties.getMaxHistoryMessages()))
                .map(this::toResponse)
                .collect(Collectors.toList());
    }

    private ChatPendingAction savePendingActionInternal(String sessionId, String actionId, String actionType,
                                                        ChatPendingActionPayload payload) {
        ChatPendingAction action = new ChatPendingAction();
        action.setActionId(StringUtils.hasText(actionId) ? actionId : UUID.randomUUID().toString());
        action.setSessionId(sessionId);
        action.setActionType(actionType);
        action.setActionPayloadJson(writeJson(payload));
        action.setStatus("PENDING");
        action.setCreatedAt(LocalDateTime.now());
        chatPendingActionMapper.insert(action);
        return action;
    }

    @Override
    public ChatPendingAction savePendingAction(TenantContext tenant, String sessionId, String actionId,
                                               String actionType, ChatPendingActionPayload payload) {
        requireOwnedSession(tenant, sessionId);
        return savePendingActionInternal(sessionId, actionId, actionType, payload);
    }

    private ChatPendingAction getPendingActionInternal(String sessionId, String actionId) {
        ChatPendingAction action = chatPendingActionMapper.selectOne(new LambdaQueryWrapper<ChatPendingAction>()
                .eq(ChatPendingAction::getSessionId, sessionId)
                .eq(ChatPendingAction::getActionId, actionId)
                .last("limit 1"));
        if (action == null) {
            throw new BusinessException(404, "待确认动作不存在");
        }
        return action;
    }

    @Override
    public ChatPendingAction getPendingAction(TenantContext tenant, String sessionId, String actionId) {
        requireOwnedSession(tenant, sessionId);
        return getPendingActionInternal(sessionId, actionId);
    }

    private void markPendingActionStatusInternal(String sessionId, String actionId, String status) {
        ChatPendingAction action = chatPendingActionMapper.selectOne(new LambdaQueryWrapper<ChatPendingAction>()
                .eq(ChatPendingAction::getSessionId, sessionId)
                .eq(ChatPendingAction::getActionId, actionId)
                .last("limit 1"));
        if (action == null) {
            throw new BusinessException(404, "待确认动作不存在");
        }
        action.setStatus(status);
        action.setConfirmedAt(LocalDateTime.now());
        chatPendingActionMapper.updateById(action);
    }

    @Override
    public void markPendingActionStatus(TenantContext tenant, String sessionId, String actionId, String status) {
        requireOwnedSession(tenant, sessionId);
        markPendingActionStatusInternal(sessionId, actionId, status);
    }

    private boolean transitionPendingActionInternal(String sessionId, String actionId, String expectedStatus,
                                                    String targetStatus, String errorMessage) {
        return chatPendingActionMapper.transitionStatus(
                sessionId, actionId, expectedStatus, targetStatus, errorMessage) == 1;
    }

    @Override
    public boolean transitionPendingAction(TenantContext tenant, String sessionId, String actionId,
                                           String expectedStatus, String targetStatus, String errorMessage) {
        requireOwnedSession(tenant, sessionId);
        return transitionPendingActionInternal(sessionId, actionId, expectedStatus, targetStatus, errorMessage);
    }

    @Override
    public void verifySessionOwner(String username, String sessionId) {
        requireOwnedSession(username, sessionId);
    }

    @Override
    public TenantContext resolveTenantForSystemCallback(String sessionId) {
        ChatSession session = chatSessionMapper.selectOne(new LambdaQueryWrapper<ChatSession>()
                .eq(ChatSession::getSessionId, sessionId)
                .last("limit 1"));
        if (session == null || session.getUserId() == null) {
            throw new BusinessException(404, "会话不存在");
        }
        return new TenantContext(session.getUserId(), session.getUsername());
    }

    private ChatSession requireOwnedSession(String username, String sessionId) {
        LambdaQueryWrapper<ChatSession> query = new LambdaQueryWrapper<ChatSession>()
                .eq(ChatSession::getSessionId, sessionId);
        Long userId = currentUserId();
        if (userId != null) query.eq(ChatSession::getUserId, userId);
        else query.eq(ChatSession::getUsername, username);
        ChatSession session = chatSessionMapper.selectOne(query.last("limit 1"));
        if (session == null) {
            throw new BusinessException(404, "会话不存在");
        }
        return session;
    }

    private ChatSession requireOwnedSession(TenantContext tenant, String sessionId) {
        ChatSession session = chatSessionMapper.selectOne(new LambdaQueryWrapper<ChatSession>()
                .eq(ChatSession::getSessionId, sessionId)
                .eq(ChatSession::getUserId, tenant.userId())
                .last("limit 1"));
        if (session == null) {
            throw new BusinessException(404, "会话不存在");
        }
        return session;
    }

    private String buildDefaultSessionId(String username) {
        return "sess_" + username + "_" + chatAssistantProperties.getDefaultSessionSuffix();
    }

    private ChatMessageResponse saveMessage(String sessionId, String role, String messageType, String content, String intent, String actionId) {
        ChatMessage message = new ChatMessage();
        message.setSessionId(sessionId);
        message.setRole(role);
        message.setMessageType(messageType);
        message.setContent(content);
        message.setIntent(intent);
        message.setActionId(actionId);
        message.setCreatedAt(LocalDateTime.now());
        chatMessageMapper.insert(message);
        return toResponse(message);
    }

    private ChatMessageResponse toResponse(ChatMessage message) {
        ChatMessageResponse response = new ChatMessageResponse();
        response.setId(message.getId());
        response.setSessionId(message.getSessionId());
        response.setRole(message.getRole());
        response.setMessageType(message.getMessageType());
        response.setContent(message.getContent());
        response.setIntent(message.getIntent());
        response.setActionId(message.getActionId());
        response.setCreatedAt(message.getCreatedAt() == null ? null : message.getCreatedAt().format(TIME_FORMATTER));
        return response;
    }

    @Override
    public void saveExecutionTrace(TenantContext tenant, String sessionId, String traceJson) {
        requireOwnedSession(tenant, sessionId);
        chatSessionMapper.saveExecutionTrace(tenant.userId(), sessionId, traceJson);
    }
    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException e) {
            throw new BusinessException("聊天动作序列化失败");
        }
    }

    private Long currentUserId() {
        Object principal = SecurityContextHolder.getContext().getAuthentication() == null
                ? null : SecurityContextHolder.getContext().getAuthentication().getPrincipal();
        return principal instanceof TenantPrincipal tenantPrincipal ? tenantPrincipal.userId() : null;
    }
}
