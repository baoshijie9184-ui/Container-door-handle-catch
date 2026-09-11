package com.ruanzhu.doorhandle.module.app.stategraph.node;

import com.ruanzhu.doorhandle.module.app.service.DeepSeekClient;
import com.ruanzhu.doorhandle.module.app.stategraph.core.AgentState;
import com.ruanzhu.doorhandle.module.app.stategraph.core.Node;
import com.ruanzhu.doorhandle.module.app.stategraph.util.StateUpdater;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.*;

/**
 * 槽位检查节点 — 检查当前任务所需槽位是否完整。
 * <ul>
 *   <li>槽位不全 → LLM 生成追问 → phase=COLLECTING → EXIT_COMPLETE（等待下一轮）</li>
 *   <li>槽位完整 → phase=EXECUTING → 路由到对应 Agent 执行</li>
 * </ul>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class SlotFillingNode implements Node {

    private final DeepSeekClient deepSeekClient;

    /** 各任务类型的必填槽位 */
    private static final Map<String, Set<String>> REQUIRED_SLOTS = Map.of(
            "IMAGE_DETECTION_UPLOAD", Set.of("folderPath"),
            "IMAGE_DETECTION_START", Set.of("taskId")
    );

    @Override
    public AgentState execute(AgentState state) {
        String taskType = state.getString(AgentState.KEY_TASK_TYPE);

        // 非结构化任务（查询/闲聊）不需要槽位检查
        Set<String> required = REQUIRED_SLOTS.get(taskType);
        if (required == null || required.isEmpty()) {
            state.set(AgentState.KEY_CONVERSATION_PHASE, AgentState.PHASE_EXECUTING);
            return state;
        }

        // 用当前 slots 重新计算缺失槽位
        StateUpdater.recalculateMissingSlots(state, required);
        List<String> missing = state.getMissingSlots();

        if (missing == null || missing.isEmpty()) {
            // 槽位完整 → 执行
            state.set(AgentState.KEY_CONVERSATION_PHASE, AgentState.PHASE_EXECUTING);
            log.debug("SlotFilling: 槽位完整 taskType={}", taskType);
            return state;
        }

        // 槽位不全 → LLM 生成追问，由 Responder 统一收口
        state.set(AgentState.KEY_CONVERSATION_PHASE, AgentState.PHASE_COLLECTING);
        String question = generateFollowUpQuestion(state, missing, taskType);

        state.set(AgentState.KEY_RESULT_CONTENT, question);
        state.set(AgentState.KEY_RESULT_TYPE, "TEXT");

        log.info("SlotFilling: 追问 taskType={} missing={}", taskType, missing);
        return state;
    }

    /** 用 LLM 生成自然的追问文本 */
    private String generateFollowUpQuestion(AgentState state, List<String> missingSlots, String taskType) {
        try {
            Map<String, Object> slots = state.getSlots();
            StringBuilder ctx = new StringBuilder();
            ctx.append("任务类型: ").append(taskType).append("\n");
            if (slots != null && !slots.isEmpty()) {
                ctx.append("已提供的信息: ");
                slots.forEach((k, v) -> ctx.append(k).append("=").append(v).append(", "));
                ctx.append("\n");
            }
            ctx.append("还缺少的信息: ").append(String.join(", ", missingSlots));

            return deepSeekClient.generateSlotQuestion(ctx.toString());
        } catch (Exception e) {
            log.warn("LLM 追问生成失败，使用默认追问: {}", e.getMessage());
            return "请补充以下信息：" + String.join("、", missingSlots);
        }
    }
}
