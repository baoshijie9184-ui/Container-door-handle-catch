package com.ruanzhu.doorhandle.contracts.agent;

/** 系统模块负责账号事实；身份仅由后端构造，不由模型传入。 */
public interface AgentUserDirectory {
    record Inspector(long userId,String username,String revision) {}
    void assertSupervisor(AgentActor actor);
    boolean inspectorExists(String username);
    default Inspector inspector(String username){throw new IllegalStateException("稳定员工目录未接入");}
    /** Caller has a business transaction; the owner holds a shared account lock through its commit. */
    default Inspector lockInspector(Inspector expected){throw new IllegalStateException("员工快照锁定未接入");}
}
