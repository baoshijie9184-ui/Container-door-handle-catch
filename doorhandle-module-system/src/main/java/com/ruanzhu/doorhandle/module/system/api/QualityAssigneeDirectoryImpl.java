package com.ruanzhu.doorhandle.module.system.api;

import com.ruanzhu.doorhandle.contracts.security.QualityAssigneeDirectory;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import org.springframework.stereotype.Service;
import java.util.List;

@Service
public class QualityAssigneeDirectoryImpl implements QualityAssigneeDirectory {
    private final UserMapper users;
    private com.ruanzhu.doorhandle.contracts.agent.AgentUserDirectory accounts;
    private com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory actors;
    @org.springframework.beans.factory.annotation.Autowired
    public void setAccounts(com.ruanzhu.doorhandle.contracts.agent.AgentUserDirectory accounts,com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory actors){this.accounts=accounts;this.actors=actors;}
    public QualityAssigneeDirectoryImpl(UserMapper users) { this.users = users; }
    public List<Option> search(String keyword) {
        if(!actors.authenticated().supervisor())throw new org.springframework.security.access.AccessDeniedException("无权查询责任人账号");
        String value = keyword == null ? "" : keyword.trim();
        if (value.length() > 50) throw new IllegalArgumentException("账号搜索内容过长");
        var names=users.findQualityAssignees(value);if(names.isEmpty())return List.of();
        var records=users.selectList(new com.baomidou.mybatisplus.core.conditions.query.QueryWrapper<com.ruanzhu.doorhandle.module.system.entity.User>()
                .select("id","username","role","created_at","updated_at").in("username",names));
        var grouped=records.stream().collect(java.util.stream.Collectors.groupingBy(com.ruanzhu.doorhandle.module.system.entity.User::getUsername));
        var result=new java.util.ArrayList<Option>();
        for(String name:names){
            var matches=grouped.get(name);if(matches==null||matches.size()!=1)continue;
            try{var account=InspectorAccountSnapshot.describe(matches.get(0));result.add(new Option(account.username(),account.userId(),account.revision()));}
            catch(IllegalArgumentException changed){/* A listed account may have been removed or changed role. */}
        }
        return List.copyOf(result);
    }
    public boolean exists(String username) {
        if (username == null || username.isBlank()) return false;
        return accounts.inspectorExists(username);
    }
}
