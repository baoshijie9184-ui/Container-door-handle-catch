package com.ruanzhu.doorhandle.module.system.api;

import com.ruanzhu.doorhandle.contracts.security.QualityAssigneeDirectory;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import org.springframework.stereotype.Service;
import java.util.List;

@Service
public class QualityAssigneeDirectoryImpl implements QualityAssigneeDirectory {
    private final UserMapper users;
    public QualityAssigneeDirectoryImpl(UserMapper users) { this.users = users; }
    public List<Option> search(String keyword) {
        String value = keyword == null ? "" : keyword.trim();
        if (value.length() > 50) throw new IllegalArgumentException("账号搜索内容过长");
        return users.findQualityAssignees(value).stream().map(Option::new).toList();
    }
    public boolean exists(String username) {
        if (username == null || username.isBlank()) return false;
        var user = users.findByUsername(username);
        return user != null && ("INSPECTOR".equalsIgnoreCase(user.getRole()) || "OPERATOR".equalsIgnoreCase(user.getRole()));
    }
}
