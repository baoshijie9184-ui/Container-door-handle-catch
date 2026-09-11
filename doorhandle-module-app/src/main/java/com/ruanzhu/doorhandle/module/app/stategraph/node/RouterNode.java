package com.ruanzhu.doorhandle.module.app.stategraph.node;

import com.ruanzhu.doorhandle.module.app.config.properties.DeepSeekProperties;
import com.ruanzhu.doorhandle.module.app.dto.chat.AgentRouteDecision;
import com.ruanzhu.doorhandle.module.app.dto.chat.MultiTurnIntentResult;
import com.ruanzhu.doorhandle.module.app.service.ContextBuilder;
import com.ruanzhu.doorhandle.module.app.service.DeepSeekClient;
import com.ruanzhu.doorhandle.module.app.stategraph.core.AgentState;
import com.ruanzhu.doorhandle.module.app.stategraph.core.Node;
import com.ruanzhu.doorhandle.module.app.stategraph.util.StateUpdater;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.util.*;

/**
 * 意图路由节点 — 多轮 LLM 意图分类 + 关键字 fallback。
 * 注入对话上下文（slots + summary + recent messages），
 * 支持 NEW_TASK / SUPPLEMENT / MODIFY / FOLLOWUP / CHITCHAT 分类。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class RouterNode implements Node {

    private final DeepSeekClient deepSeekClient;
    private final DeepSeekProperties deepSeekProperties;
    private final ContextBuilder contextBuilder;

    /** 各 Agent + 操作类型对应的必填槽位 */
    private static final Map<String, Set<String>> REQUIRED_SLOTS = Map.of(
            "IMAGE_DETECTION_UPLOAD", Set.of("folderPath"),
            "IMAGE_DETECTION_START", Set.of("taskId")
    );

    @Override
    public AgentState execute(AgentState state) {
        String content = state.getString(AgentState.KEY_USER_INPUT);
        StateUpdater.nextTurn(state);

        // 尝试多轮 LLM 分类
        if (deepSeekProperties.isEnabled() && StringUtils.hasText(deepSeekProperties.getApiKey())) {
            try {
                return classifyWithContext(state, content);
            } catch (Exception e) {
                log.warn("多轮意图分类失败，回退到关键字路由: {}", e.getMessage());
            }
        }

        // Fallback: 关键字路由（无上下文感知）
        return applyKeywordRoute(state, content);
    }

    /** 多轮 LLM 意图分类 — 注入上下文，解析意图并更新槽位。 */
    private AgentState classifyWithContext(AgentState state, String content) {
        String context = contextBuilder.buildContext(state, content);
        String llmResponse = deepSeekClient.classifyIntent(context);
        MultiTurnIntentResult result = deepSeekClient.parseMultiTurnIntent(llmResponse);

        Map<String, Object> slotUpdates = result.getSlotUpdates();
        String targetAgent = result.getTargetAgent();
        String intent = result.getIntent();
        boolean isAction = result.isAction();

        log.info("多轮意图: intent={} agent={} isAction={} slots={}", intent, targetAgent, isAction, slotUpdates);

        // LLM 分类纠偏：用关键字修正明显的误分类
        targetAgent = correctAgentByKeywords(content, targetAgent);
        if (isAction && containsAny(content.toLowerCase(Locale.ROOT), "上传") && !containsAny(content.toLowerCase(Locale.ROOT), "开始检测", "启动检测")) {
            // "上传图片" 应该是 UPLOAD 流程，不是 START 流程
            if (slotUpdates != null && !slotUpdates.containsKey("folderPath") && !slotUpdates.containsKey("taskId")) {
                // 既没有 folderPath 也没有 taskId，保持原样让 SlotFilling 追问
            }
        }

        switch (intent) {
            case "NEW_TASK" -> {
                state.mergeSlots(slotUpdates);
                String taskType = resolveTaskType(targetAgent, isAction, slotUpdates);
                state.set(AgentState.KEY_TASK_TYPE, taskType);
                StateUpdater.recalculateMissingSlots(state, REQUIRED_SLOTS.get(taskType));
                state.set(AgentState.KEY_CONVERSATION_PHASE, hasMissingSlots(state)
                        ? AgentState.PHASE_COLLECTING : AgentState.PHASE_EXECUTING);
            }
            case "SUPPLEMENT", "MODIFY" -> {
                StateUpdater.applySlotUpdates(state, slotUpdates,
                        REQUIRED_SLOTS.get(state.getString(AgentState.KEY_TASK_TYPE)));
                state.set(AgentState.KEY_CONVERSATION_PHASE, hasMissingSlots(state)
                        ? AgentState.PHASE_COLLECTING : AgentState.PHASE_EXECUTING);
                // 保持原有 taskType 和 targetAgent
                String existingAgent = resolveAgentFromExistingState(state);
                if (existingAgent != null) targetAgent = existingAgent;
            }
            case "FOLLOWUP" -> {
                if (slotUpdates != null && !slotUpdates.isEmpty()) {
                    state.mergeSlots(slotUpdates);
                }
                state.set(AgentState.KEY_CONVERSATION_PHASE, AgentState.PHASE_EXECUTING);
            }
            default -> // CHITCHAT
                state.set(AgentState.KEY_CONVERSATION_PHASE, AgentState.PHASE_EXECUTING);
        }

        // 构建路由决策
        String intentStr = targetAgent + "_" + (isAction ? "ACTION" : "QUERY");
        AgentRouteDecision decision = new AgentRouteDecision();
        decision.setTargetAgent(targetAgent);
        decision.setIntent(intentStr);
        decision.setConfirmationRequired(isAction);
        decision.setNormalizedUserPrompt(content.trim().toLowerCase(Locale.ROOT));

        state.set(AgentState.KEY_ROUTE_DECISION, decision);
        state.set(AgentState.KEY_INTENT, intentStr);
        return state;
    }

    /** 关键字路由 fallback — 保持向后兼容 */
    private AgentState applyKeywordRoute(AgentState state, String content) {
        AgentRouteDecision decision = keywordRoute(content);
        state.set(AgentState.KEY_ROUTE_DECISION, decision);
        state.set(AgentState.KEY_INTENT, decision.getIntent());
        state.set(AgentState.KEY_CONVERSATION_PHASE, AgentState.PHASE_EXECUTING);
        return state;
    }

    /**
     * 关键字路由。
     */
    private AgentRouteDecision keywordRoute(String content) {
        String text = content == null ? "" : content.trim().toLowerCase(Locale.ROOT);
        AgentRouteDecision decision = new AgentRouteDecision();
        decision.setNormalizedUserPrompt(text);

        boolean writeIntent = hasWriteIntent(text);

        if (isBusinessMapQuestion(text)) {
            decision.setIntent("OPS_QUERY");
            decision.setTargetAgent("OPS");
            decision.setConfirmationRequired(false);
            return decision;
        }

        if (containsAny(text, "报表", "日报", "周报", "摘要", "统计", "趋势", "汇总", "工作量", "处置统计", "质检统计")) {
            decision.setIntent(writeIntent ? "REPORT_ACTION" : "REPORT_QUERY");
            decision.setTargetAgent("REPORT");
            decision.setConfirmationRequired(writeIntent);
            return decision;
        }

        if (containsAny(text, "检测", "图片", "图像", "漏检", "结果图", "任务进度", "采集",
                "质检", "复核", "处置", "返工", "复检", "缺陷", "证据", "工单", "批次", "队列")) {
            decision.setIntent(writeIntent ? "DETECTION_ACTION" : "DETECTION_QUERY");
            decision.setTargetAgent("DETECTION");
            decision.setConfirmationRequired(writeIntent);
            return decision;
        }

        if (containsAny(text, "设备", "人员", "员工", "模型", "评估指标", "灰度", "回滚", "发布", "默认模型", "在线状态", "采集告警")) {
            decision.setIntent(writeIntent ? "RESOURCE_ACTION" : "RESOURCE_QUERY");
            decision.setTargetAgent("RESOURCE");
            decision.setConfirmationRequired(writeIntent);
            return decision;
        }

        decision.setIntent("OPS_QUERY");
        decision.setTargetAgent("OPS");
        decision.setConfirmationRequired(false);
        return decision;
    }

    // ---- helpers ----

    /** 根据目标 Agent 和已提取的槽位推断任务类型 */
    private String resolveTaskType(String targetAgent, boolean isAction, Map<String, Object> slots) {
        if (!"DETECTION".equals(targetAgent) || !isAction) return null;
        // 有明确 taskId → 启动已有任务检测
        if (slots != null && slots.containsKey("taskId") && slots.get("taskId") != null
                && !String.valueOf(slots.get("taskId")).isBlank()) {
            return "IMAGE_DETECTION_START";
        }
        // 其他情况（包括"上传图片"）→ 上传流程
        return "IMAGE_DETECTION_UPLOAD";
    }

    /** 从已有 State 中解析之前的目标 Agent */
    private String resolveAgentFromExistingState(AgentState state) {
        AgentRouteDecision prev = state.get(AgentState.KEY_ROUTE_DECISION, AgentRouteDecision.class);
        if (prev != null && prev.getTargetAgent() != null) return prev.getTargetAgent();
        Object raw = state.get(AgentState.KEY_ROUTE_DECISION, Map.class);
        if (raw instanceof Map<?, ?> m && m.get("targetAgent") instanceof String s) return s;
        return null;
    }

    private boolean hasMissingSlots(AgentState state) {
        List<String> missing = state.getMissingSlots();
        return missing != null && !missing.isEmpty();
    }

    private boolean containsAny(String text, String... keywords) {
        for (String keyword : keywords) {
            if (text.contains(keyword)) {
                return true;
            }
        }
        return false;
    }

    private boolean hasWriteIntent(String text) {
        if (containsAny(text, "确认缺陷数", "确认缺陷率", "确认缺陷数量")) {
            return false;
        }
        if (containsAny(text, "确认执行", "确认提交", "确认处置", "确认放行", "确认返工", "确认报废", "确认复检", "确认将")) {
            return true;
        }
        return containsAny(text, "开始", "发起", "创建", "新建", "新增", "修改", "更新", "删除", "重试", "上传",
                "标记", "置为", "设为", "改为", "提交", "处置", "放行", "报废");
    }

    /**
     * 用关键字纠偏 LLM 的 Agent 分类。
     * 当 LLM 返回 OPS 但输入明显是业务资源查询时，纠正为 RESOURCE。
     * 当输入是明显闲聊（问候、感谢等）时，纠正为 OPS（对应 CHITCHAT）。
     */
    private String correctAgentByKeywords(String content, String currentAgent) {
        if (content == null) return currentAgent;
        String text = content.toLowerCase(Locale.ROOT);

        if (isBusinessMapQuestion(text)) {
            return "OPS";
        }

        // 闲聊关键字 → OPS（CHITCHAT 的默认路由目标）
        if (containsAny(text, "你好", "谢谢", "你是谁", "早上好", "晚上好", "再见", "hello", "hi", "thanks", "thank you")
                && !containsAny(text, "检测", "设备", "报表", "上传", "任务")) {
            return "OPS";
        }

        // OPS 但含检测相关关键字 → DETECTION
        if ("OPS".equals(currentAgent) && containsAny(text, "检测任务", "检测记录", "检测结果", "检测进度", "漏检",
                "质检", "复核", "处置", "返工", "复检", "缺陷", "工单", "批次", "队列")
                && !containsAny(text, "系统状态", "运行状态", "kafka", "worker", "oss", "服务状态", "健康")) {
            return "DETECTION";
        }

        // OPS 但含设备采集查询关键字（如 "DEV-0001采集了多少"）→ DETECTION
        if ("OPS".equals(currentAgent) && text.matches(".*[a-zA-Z]+-\\d+.*(?:采集|检测|图片|记录).*")) {
            return "DETECTION";
        }

        // OPS 但含资源相关关键字 → RESOURCE
        if ("OPS".equals(currentAgent) && containsAny(text, "设备", "人员", "员工", "模型",
                "评估指标", "灰度", "回滚", "默认模型", "模型发布", "采集告警")
                && !containsAny(text, "系统状态", "运行状态", "kafka", "worker", "oss", "服务状态", "健康")) {
            return "RESOURCE";
        }

        // OPS 但含"查/找 + 人名 + 信息"模式 → RESOURCE
        if ("OPS".equals(currentAgent) && text.matches(".*(?:查|找|看|查询|查看).*[\\u4e00-\\u9fff]{2,4}(?:信息|情况|资料|详情).*")) {
            return "RESOURCE";
        }

        return currentAgent;
    }

    private boolean isBusinessMapQuestion(String text) {
        return containsAny(text, "在哪", "入口", "页面", "菜单", "怎么用", "业务地图", "功能地图", "导航", "下一步");
    }
}
