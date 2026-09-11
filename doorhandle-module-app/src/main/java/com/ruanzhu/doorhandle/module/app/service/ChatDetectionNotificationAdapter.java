package com.ruanzhu.doorhandle.module.app.service;

import com.ruanzhu.doorhandle.module.detection.service.DetectionNotificationPort;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/**
 * 将检测完成事件适配到现有聊天会话；后续可随 Agent 模块独立拆分。
 */
@Component
@RequiredArgsConstructor
public class ChatDetectionNotificationAdapter implements DetectionNotificationPort {

    private final ChatSessionService chatSessionService;

    @Override
    public void notifyTaskCompleted(String sessionId, String content) {
        TenantContext tenant = chatSessionService.resolveTenantForSystemCallback(sessionId);
        chatSessionService.appendAssistantMessage(
                tenant, sessionId, content, "TEXT", "DETECTION_ACTION", null);
    }
}
