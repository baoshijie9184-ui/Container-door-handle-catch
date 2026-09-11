package com.ruanzhu.doorhandle.module.app.stategraph.core;

/**
 * StateGraph 运行时异常，携带可选的 AgentState 用于调试。
 */
public class StateGraphException extends RuntimeException {

    private final AgentState state;

    public StateGraphException(String message) {
        super(message);
        this.state = null;
    }

    public StateGraphException(String message, Throwable cause) {
        super(message, cause);
        this.state = null;
    }

    public StateGraphException(String message, AgentState state) {
        super(message);
        this.state = state;
    }

    public StateGraphException(String message, Throwable cause, AgentState state) {
        super(message, cause);
        this.state = state;
    }

    public AgentState getAgentState() {
        return state;
    }
}
