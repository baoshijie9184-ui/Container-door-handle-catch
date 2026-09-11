package com.ruanzhu.doorhandle.module.app.stategraph.core;

/**
 * StateGraph 中的节点，接收全局 State 并返回更新后的 State。
 */
@FunctionalInterface
public interface Node {

    AgentState execute(AgentState state);

    default String name() {
        return getClass().getSimpleName();
    }
}
