package com.ruanzhu.doorhandle.module.system.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.agent.BusinessMutation;
import com.ruanzhu.doorhandle.module.system.entity.User;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import jakarta.validation.constraints.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.util.*;

/** Actual account access facts. All entry paths lock the same stable IDs in the same order. */
@Service
public class AccountAccessService {
    public record Change(@NotNull Boolean enabled,@NotBlank @Pattern(regexp="SUPERVISOR|INSPECTOR") String role,
                         @NotNull @Min(0) Long expectedVersion,@NotBlank @Pattern(regexp="[A-Za-z0-9_-]{8,100}") String requestId) {}
    public record View(
            @com.fasterxml.jackson.databind.annotation.JsonSerialize(using=com.fasterxml.jackson.databind.ser.std.ToStringSerializer.class) long userId,
            String username,boolean enabled,String role,
            @com.fasterxml.jackson.databind.annotation.JsonSerialize(using=com.fasterxml.jackson.databind.ser.std.ToStringSerializer.class) long accountVersion) {}
    private final UserMapper users;
    private final JdbcTemplate jdbc;
    private final LoginEligibilityService eligibility;
    private final LoginSessionService sessions;
    @Value("${collaboration.mutations.enabled:false}") private boolean mutations;
    public AccountAccessService(UserMapper users,JdbcTemplate jdbc,LoginEligibilityService eligibility,LoginSessionService sessions){this.users=users;this.jdbc=jdbc;this.eligibility=eligibility;this.sessions=sessions;}
    public View read(TenantPrincipal actor,long id){supervisor(actor.userId(),actor.username());var user=users.selectById(id);if(user==null)throw new BusinessException(404,"账号不存在");return view(user);}
    @Transactional(rollbackFor=Exception.class,isolation=org.springframework.transaction.annotation.Isolation.READ_COMMITTED)
    @BusinessMutation(domain="ORGANIZATION",action="ACCOUNT_ACCESS",resource="arg1",version="result.accountVersion",request="arg2.requestId",supervisorOnly=true)
    public View change(TenantPrincipal principal,long id,Change command){
        if(!mutations||!sessions.enabled())throw new BusinessException(409,"账号协同管理尚未启用");
        if(command==null||command.enabled()==null||command.expectedVersion()==null||command.expectedVersion()<0||
                !Set.of("SUPERVISOR","INSPECTOR").contains(command.role())||command.requestId()==null||!command.requestId().matches("[A-Za-z0-9_-]{8,100}"))throw new BusinessException(400,"账号修改参数不正确");
        User target=lock(principal.userId(),principal.username(),id);
        if(target==null)throw new BusinessException(404,"账号不存在");
        if(!Objects.equals(target.getAccountVersion(),command.expectedVersion()))throw new BusinessException(409,"账号权限已更新，请重新读取");
        String oldRole=target.getRole();boolean enabled=Boolean.TRUE.equals(target.getEnabled());
        if(enabled==command.enabled()&&Objects.equals(oldRole,command.role()))return view(target);
        if(id==principal.userId())throw new BusinessException(409,"不能停用或降低本人的登录权限");
        if(enabled&&("SUPERVISOR".equals(oldRole)||"ADMIN".equals(oldRole))&&(!command.enabled()||!"SUPERVISOR".equals(command.role()))){
            Long count=jdbc.queryForObject("SELECT COUNT(*) FROM users WHERE enabled=TRUE AND role IN ('SUPERVISOR','ADMIN')",Long.class);
            if(count==null||count<=1)throw new BusinessException(409,"必须保留至少一名启用的主管");
        }
        if(command.enabled())eligibility.requirePersonnel(id,command.role());
        if(target.getAccountVersion()==Long.MAX_VALUE)throw new BusinessException(409,"账号版本已达到上限");
        if(jdbc.update("UPDATE users SET enabled=?,role=?,account_version=account_version+1 WHERE id=? AND account_version=?",command.enabled(),command.role(),id,command.expectedVersion())!=1)throw new BusinessException(409,"账号权限已更新");
        sessions.revokeAll(id);
        return view(users.selectById(id));
    }
    User lock(long actorId,String username,long targetId){
        if(actorId<=0||targetId<=0)throw new AccessDeniedException("账号参数无效");
        User target=null;
        for(long id:new TreeSet<>(List.of(actorId,targetId))){
            var current=users.selectOne(new LambdaQueryWrapper<User>().eq(User::getId,id).last("FOR UPDATE"));
            if(id==actorId&&(current==null||!Objects.equals(username,current.getUsername())||!Boolean.TRUE.equals(current.getEnabled())))throw new AccessDeniedException("当前账号没有账号管理权限");
            if(id==targetId)target=current;
        }
        supervisor(actorId,username);return target;
    }
    void supervisor(long id,String username){if(!"SUPERVISOR".equals(eligibility.requireCurrent(id,username).role()))throw new AccessDeniedException("仅主管可管理登录账号");}
    static View view(User user){return new View(user.getId(),user.getUsername(),Boolean.TRUE.equals(user.getEnabled()),user.getRole(),user.getAccountVersion());}
}
