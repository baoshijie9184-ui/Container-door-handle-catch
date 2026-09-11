package com.ruanzhu.doorhandle.module.app.service;

import com.ruanzhu.doorhandle.module.app.dto.chat.AgentRouteDecision;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatConfirmActionRequest;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatMessageResponse;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatSendMessageRequest;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

public interface AgentOrchestratorService {

    AgentRouteDecision decideRoute(String content);

    ChatMessageResponse handleUserMessage(String username, ChatSendMessageRequest request);

    SseEmitter streamUserMessage(String username, ChatSendMessageRequest request);

    ChatMessageResponse confirmAction(String username, ChatConfirmActionRequest request);
}
