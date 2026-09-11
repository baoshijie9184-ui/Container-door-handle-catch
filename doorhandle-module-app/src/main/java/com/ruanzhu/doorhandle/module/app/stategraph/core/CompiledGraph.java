package com.ruanzhu.doorhandle.module.app.stategraph.core;

import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import com.ruanzhu.doorhandle.module.app.stategraph.checkpoint.Checkpointer;
import lombok.extern.slf4j.Slf4j;

import java.util.*;
import java.util.stream.Collectors;

/**
 * StateGraph 编译后的执行引擎。
 * 线程安全：节点和边不可变，所有可变状态封装在 per-request 的 AgentState 中。
 */
@Slf4j
public class CompiledGraph implements Node {

    private static final String END = "__END__";

    private final Map<String, Node> nodes;
    private final Map<String, List<ConditionalEdge>> edgeIndex;
    private final String entryPoint;
    private final String fallbackNode;
    private final int maxIterations;
    private final long maxExecutionMs;
    private final int maxVisitsPerNode;
    private final int maxRepeatRoute;
    private final int maxTraceSize;
    private final Map<String, Integer> nodeMaxRetries;
    private final Checkpointer checkpointer;
    private final AgentGraphRunListener runListener;

    CompiledGraph(Map<String, Node> nodes,
                  List<ConditionalEdge> edges,
                  String entryPoint,
                  String fallbackNode,
                  int maxIterations,
                  long maxExecutionMs,
                  int maxVisitsPerNode,
                  int maxRepeatRoute,
                  int maxTraceSize,
                  Map<String, Integer> nodeMaxRetries,
                  Checkpointer checkpointer,
                  AgentGraphRunListener runListener) {
        this.nodes = Collections.unmodifiableMap(nodes);
        this.entryPoint = entryPoint;
        this.fallbackNode = fallbackNode;
        this.maxIterations = maxIterations;
        this.maxExecutionMs = maxExecutionMs;
        this.maxVisitsPerNode = maxVisitsPerNode;
        this.maxRepeatRoute = maxRepeatRoute;
        this.maxTraceSize = maxTraceSize;
        this.nodeMaxRetries = Collections.unmodifiableMap(nodeMaxRetries);
        this.checkpointer = checkpointer;
        this.runListener = runListener != null ? runListener : AgentGraphRunListener.NOOP;

        // 构建 edgeIndex：fromNode → 按 priority 排序的边列表
        Map<String, List<ConditionalEdge>> index = new LinkedHashMap<>();
        for (ConditionalEdge edge : edges) {
            index.computeIfAbsent(edge.getFromNode(), k -> new ArrayList<>()).add(edge);
        }
        // 对每个 fromNode 的边按 priority 排序
        for (List<ConditionalEdge> edgeList : index.values()) {
            edgeList.sort(Comparator.comparingInt(ConditionalEdge::getPriority));
        }
        this.edgeIndex = Collections.unmodifiableMap(index);
    }

    // ---- 作为 Node 被用作子图时 ----

    @Override
    public AgentState execute(AgentState state) {
        return invoke(state);
    }

    @Override
    public String name() {
        return "CompiledGraph";
    }

    // ---- 公开 API ----

    /**
     * 从零开始执行整张图。
     */
    public AgentState invoke(AgentState state) {
        log.info("StateGraph.invoke: thread_id={}, entry={}", state.getString(AgentState.KEY_THREAD_ID), entryPoint);
        AgentState result = runLoop(state, entryPoint);
        runListener.onRunFinished(result);
        log.info("StateGraph 执行完毕: thread_id={}, exit_reason={}, iteration={}",
                result.getString(AgentState.KEY_THREAD_ID),
                result.getString(AgentState.KEY_EXIT_REASON),
                result.getInt(AgentState.KEY_ITERATION));
        return result;
    }

    /**
     * 从 checkpoint 恢复执行。
     * @param threadId 会话 ID
     * @param resumeValues 恢复时注入的附加值（如 confirmed=true）
     */
    public AgentState resume(TenantContext tenant, String threadId, Map<String, Object> resumeValues) {
        if (checkpointer == null) {
            throw new StateGraphException("无法恢复：未配置 Checkpointer");
        }
        AgentState state = checkpointer.load(tenant, threadId);
        if (state == null) {
            throw new StateGraphException("无法恢复：未找到 thread_id=" + threadId + " 的 checkpoint");
        }
        state.set(AgentState.KEY_TENANT_USER_ID, tenant.userId());
        state.set(AgentState.KEY_USERNAME, tenant.username());
        state.setAll(resumeValues);
        String resumeNode = state.getString(AgentState.KEY_CURRENT_NODE);
        AgentState result = runLoop(state, resumeNode == null ? entryPoint : resumeNode);
        runListener.onRunFinished(result);
        return result;
    }

    // ---- 内部 ----

    private AgentState runLoop(AgentState state, String startNode) {
        String currentNode = startNode;
        long startNanos = System.nanoTime();

        while (!END.equals(currentNode)) {
            int iteration = Optional.ofNullable(state.getInt(AgentState.KEY_ITERATION)).orElse(0) + 1;
            state.set(AgentState.KEY_ITERATION, iteration);
            updateElapsed(state, startNanos);
            recordNodeVisit(state, currentNode);

            if (isExecutionTimeout(state)) {
                state = breakByGuard(state, "执行耗时超过上限: " + state.getString(AgentState.KEY_GUARD_ELAPSED_MS) + "ms");
                break;
            }

            if (iteration > maxIterations) {
                log.warn("超过最大迭代次数 {}，进入 fallback", maxIterations);
                state.set(AgentState.KEY_ERROR, "超过最大迭代次数 " + maxIterations);
                state.set(AgentState.KEY_EXIT_REASON, AgentState.EXIT_MAX_ITERATIONS);
                if (fallbackNode != null && nodes.containsKey(fallbackNode)) {
                    state = executeWithRetry(nodes.get(fallbackNode), state);
                }
                saveCheckpoint(state);
                break;
            }

            if (isNodeVisitGuardTriggered(state, currentNode)) {
                state = breakByGuard(state, "节点重复执行次数过多: " + currentNode);
                break;
            }

            Node node = nodes.get(currentNode);
            if (node == null) {
                log.error("节点不存在: {}", currentNode);
                state.set(AgentState.KEY_ERROR, "节点不存在: " + currentNode);
                state.set(AgentState.KEY_EXIT_REASON, AgentState.EXIT_ERROR);
                if (fallbackNode != null && nodes.containsKey(fallbackNode)) {
                    state = executeWithRetry(nodes.get(fallbackNode), state);
                }
                saveCheckpoint(state);
                break;
            }

            log.debug("执行节点: {} (iteration={})", currentNode, iteration);
            try {
                state = executeWithRetry(node, state);
            } catch (Exception e) {
                log.error("节点 {} 执行失败（所有重试已耗尽）: {}", currentNode, e.getMessage());
                state.set(AgentState.KEY_ERROR, "节点 " + currentNode + " 执行失败: " + e.getMessage());
                state.set(AgentState.KEY_EXIT_REASON, AgentState.EXIT_ERROR);
                if (fallbackNode != null && nodes.containsKey(fallbackNode)) {
                    state = executeWithRetry(nodes.get(fallbackNode), state);
                }
                saveCheckpoint(state);
                break;
            }

            // 每次节点执行后保存 checkpoint
            saveCheckpoint(state);

            // 检查是否需要中断
            String exitReason = state.getString(AgentState.KEY_EXIT_REASON);
            if (AgentState.EXIT_PENDING_CONFIRMATION.equals(exitReason)) {
                log.info("暂停等待用户确认: thread_id={}", state.getString(AgentState.KEY_THREAD_ID));
                break;
            }
            if (AgentState.EXIT_COMPLETE.equals(exitReason)) {
                break;
            }

            // 路由到下一个节点
            String nextNode = route(currentNode, state);
            recordRoute(state, currentNode, nextNode);
            if (isRouteRepeatGuardTriggered(state)) {
                state = breakByGuard(state, "路由重复跳转次数过多: " + state.getString(AgentState.KEY_LAST_ROUTE));
                break;
            }
            currentNode = nextNode;
        }

        return state;
    }

    /**
     * 带重试的节点执行，指数退避。
     */
    private AgentState executeWithRetry(Node node, AgentState state) {
        int maxRetries = nodeMaxRetries.getOrDefault(state.getString(AgentState.KEY_CURRENT_NODE), 0);
        int attempt = 0;

        while (true) {
            try {
                return node.execute(state);
            } catch (Exception e) {
                attempt++;
                if (attempt > maxRetries) {
                    throw e;
                }
                long delayMs = 500L * (1L << (attempt - 1)); // 500ms, 1s, 2s, ...
                log.warn("节点 {} 执行失败 (attempt {}/{}), {}ms 后重试: {}",
                        node.name(), attempt, maxRetries, delayMs, e.getMessage());
                try {
                    Thread.sleep(delayMs);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    throw new StateGraphException("重试被中断", ie, state);
                }
            }
        }
    }

    /**
     * 路由逻辑：
     * 1. 如果 State 中显式设置了 next_node，优先使用
     * 2. 否则评估条件边，按 priority 升序，首个匹配的胜出
     * 3. 无匹配则返回 END
     */
    private String route(String currentNode, AgentState state) {
        // 显式覆盖
        String nextNode = state.getString(AgentState.KEY_NEXT_NODE);
        if (nextNode != null) {
            state.set(AgentState.KEY_NEXT_NODE, null); // 清除，避免影响后续路由
            return nextNode;
        }

        // 评估条件边
        List<ConditionalEdge> edges = edgeIndex.get(currentNode);
        if (edges != null) {
            for (ConditionalEdge edge : edges) {
                if (edge.matches(state)) {
                    log.debug("路由: {} -> {} (matched)", currentNode, edge.getTargetNode());
                    return edge.getTargetNode();
                }
            }
        }

        log.debug("路由: {} -> END (no match)", currentNode);
        return END;
    }

    @SuppressWarnings("unchecked")
    private void recordNodeVisit(AgentState state, String currentNode) {
        List<String> trace = state.get(AgentState.KEY_NODE_TRACE, List.class);
        if (trace == null) {
            trace = new ArrayList<>();
        } else {
            trace = new ArrayList<>(trace);
        }
        trace.add(currentNode);
        state.set(AgentState.KEY_NODE_TRACE, tail(trace));

        Map<String, Integer> visits = state.get(AgentState.KEY_NODE_VISIT_COUNT, Map.class);
        if (visits == null) {
            visits = new LinkedHashMap<>();
        } else {
            visits = new LinkedHashMap<>(visits);
        }
        visits.put(currentNode, visits.getOrDefault(currentNode, 0) + 1);
        state.set(AgentState.KEY_NODE_VISIT_COUNT, visits);
    }

    @SuppressWarnings("unchecked")
    private void recordRoute(AgentState state, String currentNode, String nextNode) {
        String route = currentNode + "->" + nextNode;
        List<String> trace = state.get(AgentState.KEY_ROUTE_TRACE, List.class);
        if (trace == null) {
            trace = new ArrayList<>();
        } else {
            trace = new ArrayList<>(trace);
        }
        trace.add(route);
        state.set(AgentState.KEY_ROUTE_TRACE, tail(trace));

        String lastRoute = state.getString(AgentState.KEY_LAST_ROUTE);
        int repeatCount = route.equals(lastRoute)
                ? Optional.ofNullable(state.getInt(AgentState.KEY_ROUTE_REPEAT_COUNT)).orElse(0) + 1
                : 1;
        state.set(AgentState.KEY_LAST_ROUTE, route);
        state.set(AgentState.KEY_ROUTE_REPEAT_COUNT, repeatCount);
    }

    @SuppressWarnings("unchecked")
    private boolean isNodeVisitGuardTriggered(AgentState state, String currentNode) {
        if (currentNode.equals(fallbackNode)) {
            return false;
        }
        Map<String, Integer> visits = state.get(AgentState.KEY_NODE_VISIT_COUNT, Map.class);
        if (visits == null) {
            return false;
        }
        Integer count = visits.get(currentNode);
        return count != null && count > maxVisitsPerNode;
    }

    private boolean isRouteRepeatGuardTriggered(AgentState state) {
        return Optional.ofNullable(state.getInt(AgentState.KEY_ROUTE_REPEAT_COUNT)).orElse(0) > maxRepeatRoute;
    }

    private boolean isExecutionTimeout(AgentState state) {
        return Optional.ofNullable(state.getInt(AgentState.KEY_GUARD_ELAPSED_MS)).orElse(0) > maxExecutionMs;
    }

    private AgentState breakByGuard(AgentState state, String guardReason) {
        log.warn("StateGraph 触发运行守卫: thread_id={}, reason={}, trace={}",
                state.getString(AgentState.KEY_THREAD_ID), guardReason, state.get(AgentState.KEY_NODE_TRACE, List.class));
        state.set(AgentState.KEY_GUARD_REASON, guardReason);
        state.set(AgentState.KEY_ERROR, guardReason);
        state.set(AgentState.KEY_EXIT_REASON, AgentState.EXIT_GUARD_BREAK);
        if (fallbackNode != null && nodes.containsKey(fallbackNode)) {
            state = executeWithRetry(nodes.get(fallbackNode), state);
        }
        saveCheckpoint(state);
        return state;
    }

    private void saveCheckpoint(AgentState state) {
        if (checkpointer == null) {
            return;
        }
        try {
            checkpointer.save(state.requireTenantContext(), state.getString(AgentState.KEY_THREAD_ID), state);
        } catch (Exception e) {
            log.warn("Checkpoint 保存失败: {}", e.getMessage());
        }
    }

    private List<String> tail(List<String> values) {
        int from = Math.max(0, values.size() - maxTraceSize);
        return new ArrayList<>(values.subList(from, values.size()));
    }

    private void updateElapsed(AgentState state, long startNanos) {
        long elapsedMs = (System.nanoTime() - startNanos) / 1_000_000L;
        state.set(AgentState.KEY_GUARD_ELAPSED_MS, elapsedMs);
    }

    // ---- 用于调试 ----

    @Override
    public String toString() {
        String nodesStr = nodes.keySet().stream()
                .map(n -> "  " + n + (n.equals(entryPoint) ? " [ENTRY]" : "") + (n.equals(fallbackNode) ? " [FALLBACK]" : ""))
                .collect(Collectors.joining("\n"));
        String edgesStr = edgeIndex.values().stream()
                .flatMap(List::stream)
                .map(e -> "  " + e.getFromNode() + " -> " + e.getTargetNode() + " (priority=" + e.getPriority() + ")")
                .collect(Collectors.joining("\n"));
        return "StateGraph[\nNodes:\n" + nodesStr + "\nEdges:\n" + edgesStr + "\n]";
    }
}
