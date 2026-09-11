package com.ruanzhu.doorhandle.module.app.stategraph.core;

import com.ruanzhu.doorhandle.module.app.stategraph.checkpoint.Checkpointer;
import com.ruanzhu.doorhandle.module.app.config.properties.AgentGraphGuardProperties;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * StateGraph Builder — 用 Fluent API 组装节点和边，编译为可执行的 CompiledGraph。
 */
public class StateGraph {

    private final Map<String, Node> nodes = new LinkedHashMap<>();
    private final List<ConditionalEdge> conditionalEdges = new ArrayList<>();
    private String entryPoint;
    private String fallbackNode;
    private int maxIterations = 15;
    private long maxExecutionMs = 15000L;
    private int maxVisitsPerNode = 4;
    private int maxRepeatRoute = 3;
    private int maxTraceSize = 24;
    private final Map<String, Integer> nodeMaxRetries = new LinkedHashMap<>();
    private AgentGraphRunListener runListener = AgentGraphRunListener.NOOP;

    public StateGraph addNode(String name, Node node) {
        if (nodes.containsKey(name)) {
            throw new StateGraphException("节点名称重复: " + name);
        }
        nodes.put(name, state -> {
            state.set(AgentState.KEY_CURRENT_NODE, name);
            return node.execute(state);
        });
        return this;
    }

    /**
     * 将子图作为单一节点加入，主图将其视为黑盒节点。
     */
    public StateGraph addSubgraph(String name, StateGraph subGraph) {
        return addNode(name, subGraph.compile());
    }

    public StateGraph setEntryPoint(String name) {
        this.entryPoint = name;
        return this;
    }

    public StateGraph setFallbackNode(String name) {
        this.fallbackNode = name;
        return this;
    }

    public StateGraph setMaxIterations(int max) {
        this.maxIterations = max;
        return this;
    }

    public StateGraph setGuardProperties(AgentGraphGuardProperties guardProperties) {
        if (guardProperties == null) {
            return this;
        }
        this.maxExecutionMs = positiveOrDefault(guardProperties.getMaxExecutionMs(), this.maxExecutionMs);
        this.maxVisitsPerNode = positiveOrDefault(guardProperties.getMaxVisitsPerNode(), this.maxVisitsPerNode);
        this.maxRepeatRoute = positiveOrDefault(guardProperties.getMaxRepeatRoute(), this.maxRepeatRoute);
        this.maxTraceSize = positiveOrDefault(guardProperties.getMaxTraceSize(), this.maxTraceSize);
        return this;
    }

    public StateGraph setNodeRetry(String nodeName, int maxRetries) {
        nodeMaxRetries.put(nodeName, maxRetries);
        return this;
    }

    public StateGraph setRunListener(AgentGraphRunListener runListener) {
        this.runListener = runListener != null ? runListener : AgentGraphRunListener.NOOP;
        return this;
    }

    /**
     * 添加条件边：当 condition 匹配时从 fromNode 路由到 targetNode。
     * 多条边按 priority 升序评估。
     */
    public StateGraph addConditionalEdge(String fromNode,
                                          java.util.function.Predicate<AgentState> condition,
                                          String targetNode) {
        return addConditionalEdge(fromNode, condition, targetNode, 10);
    }

    /**
     * 添加带优先级的条件边。priority 越低越优先匹配。
     */
    public StateGraph addConditionalEdge(String fromNode,
                                          java.util.function.Predicate<AgentState> condition,
                                          String targetNode,
                                          int priority) {
        conditionalEdges.add(new ConditionalEdge(fromNode, condition, targetNode, priority));
        return this;
    }

    /** 添加无条件边 */
    public StateGraph addEdge(String fromNode, String toNode) {
        conditionalEdges.add(ConditionalEdge.always(fromNode, toNode));
        return this;
    }

    /** 编译为无 Checkpointer 的图（状态不持久化） */
    public CompiledGraph compile() {
        return compile(null);
    }

    /** 编译为带 Checkpointer 的图（每个节点执行后自动保存状态） */
    public CompiledGraph compile(Checkpointer checkpointer) {
        if (entryPoint == null) {
            throw new StateGraphException("入口节点未设置，请调用 setEntryPoint()");
        }
        if (!nodes.containsKey(entryPoint)) {
            throw new StateGraphException("入口节点不存在: " + entryPoint);
        }
        if (fallbackNode != null && !nodes.containsKey(fallbackNode)) {
            throw new StateGraphException("Fallback 节点不存在: " + fallbackNode);
        }
        return new CompiledGraph(
                new LinkedHashMap<>(nodes),
                new ArrayList<>(conditionalEdges),
                entryPoint,
                fallbackNode,
                maxIterations,
                maxExecutionMs,
                maxVisitsPerNode,
                maxRepeatRoute,
                maxTraceSize,
                new LinkedHashMap<>(nodeMaxRetries),
                checkpointer,
                runListener
        );
    }

    private static int positiveOrDefault(Integer value, int defaultValue) {
        return value != null && value > 0 ? value : defaultValue;
    }

    private static long positiveOrDefault(Long value, long defaultValue) {
        return value != null && value > 0 ? value : defaultValue;
    }
}
