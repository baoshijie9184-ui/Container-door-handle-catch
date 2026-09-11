package com.ruanzhu.doorhandle.module.app.stategraph.core;

import java.util.function.Predicate;

/**
 * 条件路由边：从 fromNode 出发，当 condition 匹配时路由到 targetNode。
 * 多条边按 priority 升序评估，首个匹配的边胜出。
 */
public class ConditionalEdge {

    private final String fromNode;
    private final Predicate<AgentState> condition;
    private final String targetNode;
    private final int priority;

    public ConditionalEdge(String fromNode, Predicate<AgentState> condition, String targetNode, int priority) {
        this.fromNode = fromNode;
        this.condition = condition;
        this.targetNode = targetNode;
        this.priority = priority;
    }

    /** 无条件边，总是匹配，优先级最低 */
    public static ConditionalEdge always(String fromNode, String targetNode) {
        return new ConditionalEdge(fromNode, s -> true, targetNode, Integer.MAX_VALUE);
    }

    public boolean matches(AgentState state) {
        return condition.test(state);
    }

    public String getFromNode() { return fromNode; }
    public String getTargetNode() { return targetNode; }
    public int getPriority() { return priority; }
}
