package com.ruanzhu.doorhandle.module.app.stategraph.core;

/**
 * StateGraph 运行事件监听器，用于把执行器与监控统计解耦。
 */
public interface AgentGraphRunListener {

    AgentGraphRunListener NOOP = state -> {
    };

    void onRunFinished(AgentState state);
}
