package com.ruanzhu.doorhandle.module.app.stategraph.node;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.app.dto.chat.AgentRouteDecision;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatPendingActionPayload;
import com.ruanzhu.doorhandle.module.app.service.ChatSessionService;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import com.ruanzhu.doorhandle.module.app.service.agent.DetectionAgentService;
import com.ruanzhu.doorhandle.module.app.service.agent.ReportAgentService;
import com.ruanzhu.doorhandle.module.app.service.agent.ResourceAgentService;
import com.ruanzhu.doorhandle.module.app.stategraph.core.AgentState;
import com.ruanzhu.doorhandle.module.app.stategraph.core.Node;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.UUID;

/**
 * 人工确认节点 — 实现中断/恢复模式。
 *
 * 首次进入（confirmed != true）：创建 ChatPendingAction，设置 exit_reason = PENDING_CONFIRMATION，
 * CompiledGraph.runLoop() 检测到后中断执行并保存 checkpoint。
 *
 * 恢复进入（confirmed == true）：透传状态，让路由继续到对应的 AgentNode 执行实际操作。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class HumanConfirmNode implements Node {

    private final ChatSessionService chatSessionService;
    private final DetectionAgentService detectionAgentService;
    private final ResourceAgentService resourceAgentService;
    private final ReportAgentService reportAgentService;
    private final ObjectMapper objectMapper;

    @Override
    public AgentState execute(AgentState state) {
        Boolean confirmed = state.getBool(AgentState.KEY_CONFIRMED);

        if (Boolean.TRUE.equals(confirmed)) {
            // 恢复路径 — 用户已确认，通过
            log.info("HumanConfirmNode: 用户已确认，继续执行");
            state.set(AgentState.KEY_EXIT_REASON, null); // 清除，让循环继续
            return state;
        }

        // 首次路径 — 需要确认
        AgentRouteDecision decision = state.get(AgentState.KEY_ROUTE_DECISION, AgentRouteDecision.class);
        if (decision == null) {
            // 无路由决策时使用 intent 构建简单决策
            decision = new AgentRouteDecision();
            decision.setIntent(state.getString(AgentState.KEY_INTENT));
        }

        String username = state.getString(AgentState.KEY_USERNAME);
        String userInput = state.getString(AgentState.KEY_USER_INPUT);
        String sessionId = state.getString(AgentState.KEY_THREAD_ID);

        // 创建 pending action
        String actionId = UUID.randomUUID().toString();
        ChatPendingActionPayload payload = new ChatPendingActionPayload();
        payload.setUsername(username);
        payload.setUserPrompt(userInput);
        payload.setIntent(decision.getIntent());
        payload.setTargetAgent(decision.getTargetAgent());

        TenantContext tenant = state.requireTenantContext();
        chatSessionService.savePendingAction(tenant, sessionId, actionId, decision.getIntent(), payload);

        // 构建预览消息
        String preview = buildPreviewMessage(decision, userInput);

        state.set(AgentState.KEY_PENDING_ACTION_ID, actionId);
        state.set(AgentState.KEY_RESULT_CONTENT, preview);
        state.set(AgentState.KEY_RESULT_TYPE, "PENDING_ACTION");
        state.set(AgentState.KEY_EXIT_REASON, AgentState.EXIT_PENDING_CONFIRMATION);
        return state;
    }

    private String buildPreviewMessage(AgentRouteDecision decision, String prompt) {
        if (decision.getTargetAgent() == null) return "这个操作需要你确认后再执行。";
        return switch (decision.getTargetAgent()) {
            case "DETECTION" -> detectionAgentService.previewAction(prompt);
            case "RESOURCE" -> resourceAgentService.previewAction(prompt);
            case "REPORT" -> reportAgentService.previewAction(prompt);
            default -> "这个操作需要你确认后再执行。";
        };
    }
}
