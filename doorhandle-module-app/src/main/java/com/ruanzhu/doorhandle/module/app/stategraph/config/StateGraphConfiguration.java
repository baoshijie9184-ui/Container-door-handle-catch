package com.ruanzhu.doorhandle.module.app.stategraph.config;

import com.ruanzhu.doorhandle.module.app.dto.chat.AgentRouteDecision;
import com.ruanzhu.doorhandle.module.app.config.properties.AgentGraphGuardProperties;
import com.ruanzhu.doorhandle.module.app.service.AgentGraphRunMonitor;
import com.ruanzhu.doorhandle.module.app.stategraph.checkpoint.MySqlCheckpointer;
import com.ruanzhu.doorhandle.module.app.stategraph.core.AgentState;
import com.ruanzhu.doorhandle.module.app.stategraph.core.CompiledGraph;
import com.ruanzhu.doorhandle.module.app.stategraph.core.StateGraph;
import com.ruanzhu.doorhandle.module.app.stategraph.node.*;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.Map;

/**
 * 组装完整的聊天 StateGraph，注册为 Spring Bean。
 */
@Configuration
public class StateGraphConfiguration {

    @Bean
    public CompiledGraph chatGraph(
            RouterNode routerNode,
            DetectionAgentNode detectionNode,
            ResourceAgentNode resourceNode,
            ReportAgentNode reportNode,
            OpsAgentNode opsNode,
            HumanConfirmNode humanConfirmNode,
            ResponderNode responderNode,
            FallbackNode fallbackNode,
            SlotFillingNode slotFillingNode,
            MySqlCheckpointer checkpointer,
            AgentGraphGuardProperties guardProperties,
            AgentGraphRunMonitor runMonitor) {

        return new StateGraph()
                .addNode("router", routerNode)
                .addNode("detection", detectionNode)
                .addNode("resource", resourceNode)
                .addNode("report", reportNode)
                .addNode("ops", opsNode)
                .addNode("confirm", humanConfirmNode)
                .addNode("responder", responderNode)
                .addNode("fallback", fallbackNode)
                .addNode("slotFilling", slotFillingNode)
                .setEntryPoint("router")
                .setFallbackNode("fallback")
                .setMaxIterations(15)
                .setGuardProperties(guardProperties)
                .setRunListener(runMonitor)
                .setNodeRetry("router", 2)
                // Router → SlotFilling（槽位收集阶段，最高优先级）
                .addConditionalEdge("router",
                        s -> isPhase(s, AgentState.PHASE_COLLECTING), "slotFilling")
                // Router → Agent (QUERY) 或 Confirm (ACTION)
                .addConditionalEdge("router",
                        s -> isIntent(s, "DETECTION_QUERY"), "detection")
                .addConditionalEdge("router",
                        s -> isIntent(s, "DETECTION_ACTION"), "confirm")
                .addConditionalEdge("router",
                        s -> isIntent(s, "RESOURCE_QUERY"), "resource")
                .addConditionalEdge("router",
                        s -> isIntent(s, "RESOURCE_ACTION"), "confirm")
                .addConditionalEdge("router",
                        s -> isIntent(s, "REPORT_QUERY"), "report")
                .addConditionalEdge("router",
                        s -> isIntent(s, "REPORT_ACTION"), "confirm")
                .addConditionalEdge("router",
                        s -> isIntent(s, "OPS_QUERY"), "ops")
                // Router fallback → OPS
                .addEdge("router", "ops")
                // SlotFilling → Responder（槽位仍不全，追问用户）
                .addConditionalEdge("slotFilling",
                        s -> isPhase(s, AgentState.PHASE_COLLECTING), "responder")
                // SlotFilling → Agent/Confirm（槽位完整，继续执行）
                .addConditionalEdge("slotFilling",
                        s -> isIntent(s, "DETECTION_QUERY"), "detection")
                .addConditionalEdge("slotFilling",
                        s -> isIntent(s, "DETECTION_ACTION"), "confirm")
                .addConditionalEdge("slotFilling",
                        s -> isIntent(s, "RESOURCE_QUERY"), "resource")
                .addConditionalEdge("slotFilling",
                        s -> isIntent(s, "RESOURCE_ACTION"), "confirm")
                .addConditionalEdge("slotFilling",
                        s -> isIntent(s, "REPORT_QUERY"), "report")
                .addConditionalEdge("slotFilling",
                        s -> isIntent(s, "REPORT_ACTION"), "confirm")
                .addConditionalEdge("slotFilling",
                        s -> isIntent(s, "OPS_QUERY"), "ops")
                // SlotFilling fallback → responder
                .addEdge("slotFilling", "responder")
                // Agent → Responder
                .addEdge("detection", "responder")
                .addEdge("resource", "responder")
                .addEdge("report", "responder")
                .addEdge("ops", "responder")
                // Confirm 恢复后 → 对应 Agent（根据 route_decision 中的 targetAgent）
                .addConditionalEdge("confirm",
                        s -> isTargetAgent(s, "DETECTION"), "detection")
                .addConditionalEdge("confirm",
                        s -> isTargetAgent(s, "RESOURCE"), "resource")
                .addConditionalEdge("confirm",
                        s -> isTargetAgent(s, "REPORT"), "report")
                .compile(checkpointer);
    }

    private static boolean isPhase(AgentState state, String phase) {
        return phase.equals(state.getString(AgentState.KEY_CONVERSATION_PHASE));
    }

    private static boolean isIntent(AgentState state, String intent) {
        return intent.equals(state.getString(AgentState.KEY_INTENT));
    }

    @SuppressWarnings("unchecked")
    private static boolean isTargetAgent(AgentState state, String agent) {
        AgentRouteDecision decision = state.get(AgentState.KEY_ROUTE_DECISION, AgentRouteDecision.class);
        if (decision != null) {
            return agent.equals(decision.getTargetAgent());
        }
        // 从 MySQL checkpoint 恢复后 route_decision 是 Map，需兼容处理
        Object raw = state.get(AgentState.KEY_ROUTE_DECISION, Map.class);
        if (raw instanceof Map) {
            Object targetAgent = ((Map<String, Object>) raw).get("targetAgent");
            return agent.equals(targetAgent);
        }
        return false;
    }
}
