package com.ruanzhu.doorhandle.module.system.api;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import org.springframework.stereotype.Service;

@Service
public class AgentUserDirectoryImpl implements AgentUserDirectory {
    private final UserMapper users;
    private com.ruanzhu.doorhandle.module.system.service.LoginEligibilityService eligibility;
    private com.ruanzhu.doorhandle.module.system.security.LoginSessionProperties sessions;
    public AgentUserDirectoryImpl(UserMapper users) { this.users = users; }
    @org.springframework.beans.factory.annotation.Autowired
    public void eligibility(com.ruanzhu.doorhandle.module.system.service.LoginEligibilityService value,
            com.ruanzhu.doorhandle.module.system.security.LoginSessionProperties properties){eligibility=value;sessions=properties;}
    private String currentRole(com.ruanzhu.doorhandle.module.system.entity.User user,boolean lock){
        try{return (lock?eligibility.lockCurrent(user.getId(),user.getUsername()):eligibility.requireCurrent(user.getId(),user.getUsername())).role();}
        catch(org.springframework.security.core.AuthenticationException denied){throw new SecurityException("账号不具备当前岗位资格",denied);}
    }
    public void assertSupervisor(AgentActor actor) {
        actor.requireSupervisor();
        var query=new com.baomidou.mybatisplus.core.conditions.query.QueryWrapper<com.ruanzhu.doorhandle.module.system.entity.User>().eq("id",actor.userId());
        if(org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive())query.last(sessions!=null&&sessions.isEnabled()?"FOR UPDATE":"FOR SHARE");
        var current = users.selectOne(query);
        if(sessions!=null&&sessions.isEnabled()){
            if(current==null||!actor.username().equals(current.getUsername())||!"SUPERVISOR".equals(currentRole(current,org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive())))
                throw new SecurityException("当前账号没有主管分配权限");
            return;
        }
        if (current == null || !actor.username().equals(current.getUsername())
                || !("SUPERVISOR".equalsIgnoreCase(current.getRole()) || "ADMIN".equalsIgnoreCase(current.getRole())))
            throw new SecurityException("当前账号没有主管分配权限");
    }
    public boolean inspectorExists(String username) {
        try{inspector(username);return true;}catch(IllegalArgumentException|SecurityException unavailable){return false;}
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
        var user=users.selectOne(new com.baomidou.mybatisplus.core.conditions.query.QueryWrapper<com.ruanzhu.doorhandle.module.system.entity.User>().eq("id",expected.userId()).last(sessions!=null&&sessions.isEnabled()?"FOR UPDATE":"FOR SHARE"));
        if(user==null||!expected.equals(describe(user)))throw new IllegalArgumentException("责任人账号或快照已变化，请重新确认");
        return expected;
    }
    private Inspector describe(com.ruanzhu.doorhandle.module.system.entity.User user){
        if(sessions!=null&&sessions.isEnabled()){
            if(!"INSPECTOR".equals(currentRole(user,org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive())))throw new IllegalArgumentException("责任人不具备检测岗位资格");
            // A legacy account may be an inspector only through its explicit eligibility mapping.
            var account=BusinessAccountSnapshot.describe(user);
            return new Inspector(account.userId(),account.username(),account.revision());
        }
        return InspectorAccountSnapshot.describe(user);
    }
}
