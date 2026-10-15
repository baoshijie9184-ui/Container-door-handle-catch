package com.ruanzhu.doorhandle.contracts.agent;

/** 系统模块负责账号事实；身份仅由后端构造，不由模型传入。 */
public interface AgentUserDirectory {
    void assertSupervisor(AgentActor actor);
    boolean inspectorExists(String username);
}
