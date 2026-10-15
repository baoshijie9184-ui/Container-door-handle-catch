package com.ruanzhu.doorhandle.module.app.service;

import com.ruanzhu.doorhandle.contracts.agent.AgentConversationApi;
import com.ruanzhu.doorhandle.module.app.dto.chat.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/** 会话持久化与 HTTP 适配；Agent 执行仅通过 contracts 门面。 */
public interface ChatConversationService {
    ChatMessageResponse handleUserMessage(String username, ChatSendMessageRequest request);
    SseEmitter streamUserMessage(String username, ChatSendMessageRequest request);
    ChatMessageResponse confirmAction(String username, ChatConfirmActionRequest request);
    AgentConversationApi.Status status(String username);
}
