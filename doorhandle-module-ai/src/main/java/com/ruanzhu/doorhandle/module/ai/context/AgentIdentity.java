package com.ruanzhu.doorhandle.module.ai.context;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.Authentication;

public final class AgentIdentity {
    private AgentIdentity() {}
    public static AgentActor from(Authentication authentication) {
        if (authentication == null || !authentication.isAuthenticated()
                || !(authentication.getPrincipal() instanceof TenantPrincipal principal)) {
            throw new AccessDeniedException("请使用有效账号登录");
        }
        var roles = authentication.getAuthorities().stream().map(a -> a.getAuthority()).toList();
        AgentActor.Role role;
        if (roles.contains("ROLE_SUPERVISOR")) role = AgentActor.Role.SUPERVISOR;
        else if (roles.contains("ROLE_INSPECTOR")) role = AgentActor.Role.INSPECTOR;
        else throw new AccessDeniedException("当前账号没有检测助手权限");
        return new AgentActor(principal.userId(), principal.username(), role);
    }
}
