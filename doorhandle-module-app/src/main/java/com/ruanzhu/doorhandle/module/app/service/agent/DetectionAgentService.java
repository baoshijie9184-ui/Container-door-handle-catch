package com.ruanzhu.doorhandle.module.app.service.agent;

import com.ruanzhu.doorhandle.module.app.dto.chat.AgentExecutionResult;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;

import java.util.function.Consumer;

public interface DetectionAgentService {

    String previewAction(String userPrompt);

    AgentExecutionResult executeConfirmedAction(String userPrompt, TenantContext tenant, String sessionId);

    AgentExecutionResult answer(String userPrompt, String username);

    default AgentExecutionResult answer(String userPrompt, String username, Consumer<String> tokenConsumer) {
        return answer(userPrompt, username);
    }
}
