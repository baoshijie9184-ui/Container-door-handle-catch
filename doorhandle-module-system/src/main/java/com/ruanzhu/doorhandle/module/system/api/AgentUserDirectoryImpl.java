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
        var query=new com.baomidou.mybatisplus.core.conditions.query.QueryWrapper<com.ruanzhu.doorhandle.module.system.entity.User>().eq("id",actor.userId());
        if(org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive())query.last("FOR SHARE");
        var current = users.selectOne(query);
        if (current == null || !actor.username().equals(current.getUsername())
                || !("SUPERVISOR".equalsIgnoreCase(current.getRole()) || "ADMIN".equalsIgnoreCase(current.getRole())))
            throw new SecurityException("当前账号没有主管分配权限");
    }
    public boolean inspectorExists(String username) {
        try{inspector(username);return true;}catch(IllegalArgumentException unavailable){return false;}
    }
    @Override public Inspector inspector(String username){
        if(username==null||username.isBlank()||username.length()>64)throw new IllegalArgumentException("责任人账号无效");
        var matches=users.selectList(new com.baomidou.mybatisplus.core.conditions.query.QueryWrapper<com.ruanzhu.doorhandle.module.system.entity.User>().eq("username",username))
                .stream().filter(user->username.equals(user.getUsername())).toList();
        if(matches.size()!=1)throw new IllegalArgumentException("责任人必须是精确唯一的现有员工账号");
        return describe(matches.get(0));
    }
    @Override
    @org.springframework.transaction.annotation.Transactional(propagation=org.springframework.transaction.annotation.Propagation.MANDATORY,noRollbackFor={IllegalArgumentException.class,SecurityException.class})
    public Inspector lockInspector(Inspector expected){
        if(expected==null||expected.userId()<1||expected.revision()==null)throw new IllegalArgumentException("缺少已确认的责任人身份");
        var user=users.selectOne(new com.baomidou.mybatisplus.core.conditions.query.QueryWrapper<com.ruanzhu.doorhandle.module.system.entity.User>().eq("id",expected.userId()).last("FOR SHARE"));
        if(user==null||!expected.equals(describe(user)))throw new IllegalArgumentException("责任人账号或快照已变化，请重新确认");
        return expected;
    }
    private Inspector describe(com.ruanzhu.doorhandle.module.system.entity.User user){
        return InspectorAccountSnapshot.describe(user);
    }
}
