package com.ruanzhu.doorhandle.module.app.stategraph.util;

import com.ruanzhu.doorhandle.module.app.stategraph.core.AgentState;

import java.util.*;

/**
 * 槽位增量更新工具 — 负责对 AgentState 的槽位做增量合并，
 * 自动计算缺失槽位，管理 recentMessages 增长并触发摘要压缩。
 */
public final class StateUpdater {

    private StateUpdater() {}

    /**
     * 合并 LLM 提取的槽位更新到 state.slots，自动重新计算 missingSlots。
     */
    public static void applySlotUpdates(AgentState state, Map<String, Object> updates, Set<String> requiredSlots) {
        if (updates == null || updates.isEmpty()) return;
        state.mergeSlots(updates);
        recalculateMissingSlots(state, requiredSlots);
    }

    /**
     * 根据 taskType 对应的 requiredSlots 计算仍缺失的槽位。
     */
    public static void recalculateMissingSlots(AgentState state, Set<String> requiredSlots) {
        if (requiredSlots == null || requiredSlots.isEmpty()) {
            state.setMissingSlots(Collections.emptyList());
            return;
        }
        Map<String, Object> slots = state.getSlots();
        List<String> missing = new ArrayList<>();
        for (String key : requiredSlots) {
            Object val = slots != null ? slots.get(key) : null;
            if (val == null || (val instanceof String s && s.isBlank())) {
                missing.add(key);
            }
        }
        state.setMissingSlots(missing);
    }

    /**
     * 追加一条消息到 recentMessages，如果超过 maxRecentMessages 则返回需要触发摘要压缩的信号。
     *
     * @return true 如果触发了摘要压缩阈值
     */
    public static boolean appendMessage(AgentState state, String role, String content, int maxRecentMessages) {
        state.addRecentMessage(role, content);
        List<Map<String, Object>> msgs = state.getRecentMessages();
        return msgs != null && msgs.size() > maxRecentMessages;
    }

    /**
     * 将旧消息截断，返回被截断的消息（供 SummaryManager 使用）。
     */
    public static List<Map<String, Object>> truncateMessages(AgentState state, int keepCount) {
        List<Map<String, Object>> msgs = state.getRecentMessages();
        if (msgs == null || msgs.size() <= keepCount) return Collections.emptyList();

        int removeCount = msgs.size() - keepCount;
        List<Map<String, Object>> removed = new ArrayList<>(msgs.subList(0, removeCount));
        // 保留最后 keepCount 条
        List<Map<String, Object>> kept = new ArrayList<>(msgs.subList(removeCount, msgs.size()));
        state.set(AgentState.KEY_RECENT_MESSAGES, kept);
        return removed;
    }

    /** 获取当前轮次并自增 */
    public static int nextTurn(AgentState state) {
        Integer turn = state.getInt(AgentState.KEY_CONVERSATION_TURN);
        int next = (turn != null ? turn : 0) + 1;
        state.set(AgentState.KEY_CONVERSATION_TURN, next);
        return next;
    }
}
