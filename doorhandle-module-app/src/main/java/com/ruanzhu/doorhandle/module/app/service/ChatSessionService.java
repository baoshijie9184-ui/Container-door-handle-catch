package com.ruanzhu.doorhandle.module.app.service;

import com.ruanzhu.doorhandle.module.app.dto.chat.ChatMessageResponse;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatPendingActionPayload;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatSessionResponse;
import com.ruanzhu.doorhandle.module.app.dto.chat.ConversationTraceResponse;
import com.ruanzhu.doorhandle.module.app.entity.ChatPendingAction;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;

import java.util.List;

public interface ChatSessionService {

    ChatSessionResponse getOrCreateActiveSession(String username);

    /** 获取用户的所有会话列表（不含消息内容） */
    List<ChatSessionResponse> listUserSessions(String username);

    /** 创建新会话 */
    ChatSessionResponse createSession(String username);

    /** 获取指定会话（含消息） */
    ChatSessionResponse getSession(String username, String sessionId);

    /** 读取当前用户会话最近一次真实 AgentScope 执行轨迹。 */
    ConversationTraceResponse getExecutionTrace(String username, String sessionId);

    /** 归档会话 */
    void archiveSession(String username, String sessionId);

    /** 删除会话 */
    void deleteSession(String username, String sessionId);

    /** 重命名会话 */
    void renameSession(String username, String sessionId, String title);

    /** 置顶/取消置顶会话 */
    void togglePinSession(String username, String sessionId, boolean pinned);

    ChatMessageResponse appendUserMessage(TenantContext tenant, String sessionId, String content);

    ChatMessageResponse appendAssistantMessage(TenantContext tenant, String sessionId, String content,
                                                String messageType, String intent, String actionId);

    List<ChatMessageResponse> listMessages(String username, String sessionId);

    ChatPendingAction savePendingAction(TenantContext tenant, String sessionId, String actionId,
                                        String actionType, ChatPendingActionPayload payload);

    ChatPendingAction getPendingAction(TenantContext tenant, String sessionId, String actionId);

    void markPendingActionStatus(TenantContext tenant, String sessionId, String actionId, String status);

    boolean transitionPendingAction(TenantContext tenant, String sessionId, String actionId,
                                    String expectedStatus, String targetStatus, String errorMessage);

    void verifySessionOwner(String username, String sessionId);

    TenantContext resolveTenantForSystemCallback(String sessionId);

    void saveExecutionTrace(TenantContext tenant, String sessionId, String traceJson);
}
