package com.ruanzhu.doorhandle.contracts.agent;

/** 仅由服务端认证上下文构造，不能作为模型或 HTTP 请求参数。当前部署为单企业。 */
public record AgentActor(long userId, String username, Role role) {
    public enum Role { INSPECTOR, SUPERVISOR }

    public AgentActor {
        if (userId <= 0 || username == null || username.isBlank() || role == null) {
            throw new IllegalArgumentException("缺少有效的 Agent 身份");
        }
    }

    public boolean supervisor() { return role == Role.SUPERVISOR; }

    public void requireSupervisor() {
        if (!supervisor()) throw new SecurityException("此工具仅对检测主管开放");
    }
}
