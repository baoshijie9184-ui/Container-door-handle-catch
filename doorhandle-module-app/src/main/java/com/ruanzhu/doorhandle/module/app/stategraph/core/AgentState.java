package com.ruanzhu.doorhandle.module.app.stategraph.core;

import com.ruanzhu.doorhandle.module.system.security.TenantContext;

import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 全局状态容器 — 在 StateGraph 的所有节点之间流转。
 * 使用 ConcurrentHashMap 存储，支持未来并行节点执行。
 */
public class AgentState {

    public static final String KEY_THREAD_ID = "thread_id";
    public static final String KEY_USER_INPUT = "user_input";
    public static final String KEY_USERNAME = "username";
    public static final String KEY_TENANT_USER_ID = "tenant_user_id";
    public static final String KEY_CURRENT_NODE = "current_node";
    public static final String KEY_NEXT_NODE = "next_node";
    public static final String KEY_ROUTE_DECISION = "route_decision";
    public static final String KEY_PLAN = "plan";
    public static final String KEY_CURRENT_STEP = "current_step";
    public static final String KEY_DATA_CONTEXT = "data_context";
    public static final String KEY_LLM_RESPONSE = "llm_response";
    public static final String KEY_RESULT_CONTENT = "result_content";
    public static final String KEY_RESULT_TYPE = "result_type";
    public static final String KEY_INTENT = "intent";
    public static final String KEY_ERROR = "error";
    public static final String KEY_ITERATION = "iteration";
    public static final String KEY_CONFIRMED = "confirmed";
    public static final String KEY_PENDING_ACTION_ID = "pending_action_id";
    public static final String KEY_EXIT_REASON = "exit_reason";
    public static final String KEY_CURRENT_ROUTE = "current_route";
    public static final String KEY_CURRENT_PAGE_TITLE = "current_page_title";
    public static final String KEY_NODE_TRACE = "node_trace";
    public static final String KEY_ROUTE_TRACE = "route_trace";
    public static final String KEY_NODE_VISIT_COUNT = "node_visit_count";
    public static final String KEY_ROUTE_REPEAT_COUNT = "route_repeat_count";
    public static final String KEY_LAST_ROUTE = "last_route";
    public static final String KEY_GUARD_REASON = "guard_reason";
    public static final String KEY_GUARD_ELAPSED_MS = "guard_elapsed_ms";
    public static final String KEY_RAG_CONTEXT = "rag_context";
    public static final String KEY_STREAM_CONSUMER = "stream_consumer";
    private static final Set<String> TRANSIENT_KEYS = Set.of(KEY_STREAM_CONSUMER);

    // ---- 多轮对话字段 ----
    public static final String KEY_CONVERSATION_TURN = "turn";
    public static final String KEY_RECENT_MESSAGES = "recent_msgs";
    public static final String KEY_CONVERSATION_SUMMARY = "summary";
    public static final String KEY_TASK_TYPE = "task_type";
    public static final String KEY_SLOTS = "slots";
    public static final String KEY_MISSING_SLOTS = "missing_slots";
    public static final String KEY_INTERMEDIATE_RESULTS = "intermediate";
    public static final String KEY_CONVERSATION_PHASE = "phase";

    public static final String EXIT_COMPLETE = "COMPLETE";
    public static final String EXIT_PENDING_CONFIRMATION = "PENDING_CONFIRMATION";
    public static final String EXIT_MAX_ITERATIONS = "MAX_ITERATIONS";
    public static final String EXIT_GUARD_BREAK = "GUARD_BREAK";
    public static final String EXIT_ERROR = "ERROR";

    // ---- 对话阶段 ----
    public static final String PHASE_COLLECTING = "COLLECTING";
    public static final String PHASE_EXECUTING = "EXECUTING";
    public static final String PHASE_RESPONDING = "RESPONDING";

    private final Map<String, Object> data = new ConcurrentHashMap<>();

    public static AgentState create(String threadId, String userInput, String username) {
        AgentState state = new AgentState();
        state.set(KEY_THREAD_ID, threadId);
        state.set(KEY_USER_INPUT, userInput);
        state.set(KEY_USERNAME, username);
        state.set(KEY_ITERATION, 0);
        return state;
    }

    // ---- 类型化访问器 ----

    public String getString(String key) {
        Object value = data.get(key);
        return value != null ? value.toString() : null;
    }

    public Integer getInt(String key) {
        Object value = data.get(key);
        if (value instanceof Integer i) return i;
        if (value instanceof Number n) return n.intValue();
        if (value instanceof String s) {
            try { return Integer.parseInt(s); } catch (NumberFormatException ignored) {}
        }
        return null;
    }

    public Long getLong(String key) {
        Object value = data.get(key);
        if (value instanceof Number number) return number.longValue();
        if (value instanceof String text) {
            try { return Long.parseLong(text); } catch (NumberFormatException ignored) {}
        }
        return null;
    }

    public TenantContext requireTenantContext() {
        Long userId = getLong(KEY_TENANT_USER_ID);
        if (userId == null) {
            throw new StateGraphException("AgentState 缺少租户用户 ID");
        }
        return new TenantContext(userId, getString(KEY_USERNAME));
    }

    public Boolean getBool(String key) {
        Object value = data.get(key);
        if (value instanceof Boolean b) return b;
        if (value instanceof String s) return "true".equalsIgnoreCase(s);
        return null;
    }

    @SuppressWarnings("unchecked")
    public <T> T get(String key, Class<T> type) {
        Object value = data.get(key);
        if (value == null) return null;
        if (type.isInstance(value)) return (T) value;
        return null;
    }

    // ---- Fluent 写入 ----

    public AgentState set(String key, Object value) {
        if (value != null) {
            data.put(key, value);
        } else {
            data.remove(key);
        }
        return this;
    }

    public AgentState setAll(Map<String, Object> entries) {
        data.putAll(entries);
        return this;
    }

    public AgentState merge(AgentState other) {
        data.putAll(other.data);
        return this;
    }

    // ---- 快照 ----

    public Map<String, Object> snapshot() {
        return Collections.unmodifiableMap(new ConcurrentHashMap<>(data));
    }

    // 返回可变副本，用于序列化
    public Map<String, Object> toMap() {
        Map<String, Object> copy = new ConcurrentHashMap<>(data);
        TRANSIENT_KEYS.forEach(copy::remove);
        return copy;
    }

    // 从 Map 恢复
    @SuppressWarnings("unchecked")
    public static AgentState fromMap(Map<String, Object> map) {
        AgentState state = new AgentState();
        if (map != null) {
            map.forEach((k, v) -> {
                if (k != null) {
                    state.data.put(k, v);
                }
            });
        }
        return state;
    }

    public boolean hasKey(String key) {
        return data.containsKey(key);
    }

    // ---- 多轮对话 helpers ----

    @SuppressWarnings("unchecked")
    public Map<String, Object> getSlots() {
        Object val = data.get(KEY_SLOTS);
        if (val instanceof Map<?, ?> m) return (Map<String, Object>) m;
        return null;
    }

    public AgentState setSlots(Map<String, Object> slots) {
        data.put(KEY_SLOTS, slots != null ? new ConcurrentHashMap<>(slots) : null);
        return this;
    }

    public AgentState mergeSlots(Map<String, Object> newSlots) {
        Map<String, Object> current = getSlots();
        if (current == null) {
            current = new ConcurrentHashMap<>();
            data.put(KEY_SLOTS, current);
        }
        current.putAll(newSlots);
        return this;
    }

    @SuppressWarnings("unchecked")
    public List<Map<String, Object>> getRecentMessages() {
        Object val = data.get(KEY_RECENT_MESSAGES);
        if (val instanceof List<?> l) return (List<Map<String, Object>>) l;
        return null;
    }

    public AgentState addRecentMessage(String role, String content) {
        List<Map<String, Object>> msgs = getRecentMessages();
        if (msgs == null) {
            msgs = new java.util.ArrayList<>();
            data.put(KEY_RECENT_MESSAGES, msgs);
        }
        msgs.add(Map.of("role", role, "content", content,
                "turn", data.getOrDefault(KEY_CONVERSATION_TURN, 0)));
        return this;
    }

    @SuppressWarnings("unchecked")
    public List<String> getMissingSlots() {
        Object val = data.get(KEY_MISSING_SLOTS);
        if (val instanceof List<?> l) return (List<String>) l;
        return null;
    }

    public AgentState setMissingSlots(List<String> slots) {
        data.put(KEY_MISSING_SLOTS, slots);
        return this;
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> getIntermediateResults() {
        Object val = data.get(KEY_INTERMEDIATE_RESULTS);
        if (val instanceof Map<?, ?> m) return (Map<String, Object>) m;
        return null;
    }

    public AgentState putIntermediateResult(String key, Object value) {
        Map<String, Object> results = getIntermediateResults();
        if (results == null) {
            results = new ConcurrentHashMap<>();
            data.put(KEY_INTERMEDIATE_RESULTS, results);
        }
        results.put(key, value);
        return this;
    }
}
