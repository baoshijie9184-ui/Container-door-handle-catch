package com.ruanzhu.doorhandle.module.system.api;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import org.springframework.stereotype.Service;

@Service
public class AgentUserDirectoryImpl implements AgentUserDirectory {
    private final UserMapper users;
    public AgentUserDirectoryImpl(UserMapper users) { this.users = users; }
    public void assertSupervisor(AgentActor actor) {
        actor.requireSupervisor();
        var current = users.selectById(actor.userId());
        if (current == null || !actor.username().equals(current.getUsername())
                || !("SUPERVISOR".equalsIgnoreCase(current.getRole()) || "ADMIN".equalsIgnoreCase(current.getRole())))
            throw new SecurityException("当前账号没有主管分配权限");
    }
    public boolean inspectorExists(String username) {
        var user = users.findByUsername(username);
        return user != null && ("INSPECTOR".equalsIgnoreCase(user.getRole()) || "OPERATOR".equalsIgnoreCase(user.getRole()));
    }
}
