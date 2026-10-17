package com.ruanzhu.doorhandle.module.system.api;

import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import org.springframework.stereotype.Service;

@Service
public class BusinessUserDirectoryImpl implements BusinessUserDirectory {
    private final UserMapper users;
    public BusinessUserDirectoryImpl(UserMapper users) { this.users = users; }
    public Identity current(long userId, String username) {
        var user = users.selectById(userId);
        if (user == null || userId <= 0 || username == null || !username.equals(user.getUsername()))
            throw new SecurityException("当前账号身份已失效");
        String role=user.getRole()==null?"":user.getRole().toUpperCase(java.util.Locale.ROOT);
        if(!java.util.Set.of("SUPERVISOR","ADMIN","INSPECTOR","OPERATOR").contains(role))
            throw new SecurityException("当前账号没有业务助手权限");
        return new Identity(userId, username, "SUPERVISOR".equalsIgnoreCase(user.getRole()) || "ADMIN".equalsIgnoreCase(user.getRole()));
    }
}
