package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.organization.EmployeeDirectoryApi;
import com.ruanzhu.doorhandle.module.system.entity.User;
import com.ruanzhu.doorhandle.module.system.mapper.AccountEmployeeBindingMapper;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import com.ruanzhu.doorhandle.module.system.security.LoginSessionProperties;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import org.springframework.security.authentication.DisabledException;
import org.springframework.stereotype.Service;
import java.util.List;
import java.util.Objects;

/** Reads current account and personnel facts; unknown roles never acquire inspector access. */
@Service
public class LoginEligibilityService {
    public record Eligible(User user,String role) {}
    private final UserMapper users;
    private final AccountEmployeeBindingMapper bindings;
    private final EmployeeDirectoryApi employees;
    private final LoginSessionProperties properties;
    public LoginEligibilityService(UserMapper users,AccountEmployeeBindingMapper bindings,EmployeeDirectoryApi employees,LoginSessionProperties properties){
        this.users=users;this.bindings=bindings;this.employees=employees;this.properties=properties;
    }
    public Eligible requireCurrent(long id,String username){
        return requireCurrent(id,username,false);
    }
    /** Account writes use this before locking their session row, matching account-access changes. */
    public Eligible lockCurrent(long id,String username){return requireCurrent(id,username,true);}
    private Eligible requireCurrent(long id,String username,boolean lock){
        var user=lock?users.selectOne(new LambdaQueryWrapper<User>().eq(User::getId,id).last("FOR UPDATE")):users.selectById(id);
        if(user==null||!Objects.equals(username,user.getUsername())||!Boolean.TRUE.equals(user.getEnabled()))denied();
        String role=role(user);
        requirePersonnel(id,role,lock);
        return new Eligible(user,role);
    }
    public void requirePersonnel(long id,String role){
        requirePersonnel(id,role,false);
    }
    private void requirePersonnel(long id,String role,boolean lock){
        var binding=lock?bindings.selectLockedById(id):bindings.selectById(id);
        if(binding==null||binding.getEmployeeId()==null){
            if(!"SUPERVISOR".equals(role))denied();
        }else{
            EmployeeDirectoryApi.EmployeeIdentity employee;
            if(lock){
                try{employee=employees.lock(binding.getEmployeeId());}
                catch(com.ruanzhu.doorhandle.common.BusinessException unavailable){if(unavailable.getCode()!=404)throw unavailable;denied();return;}
            }else{
                var found=employees.findAll(List.of(binding.getEmployeeId()));
                employee=found.stream().filter(e->Objects.equals(e.id(),binding.getEmployeeId())).findFirst().orElse(null);
            }
            if(employee==null||!"ACTIVE".equals(employee.status())||
                    (!"DETECTION".equals(employee.employeeType())&& !"SUPERVISOR".equals(employee.employeeType())))denied();
            if("INSPECTOR".equals(role)&&!"DETECTION".equals(employee.employeeType()))denied();
        }
    }
    public String role(User user){
        String value=user.getRole();
        if("SUPERVISOR".equals(value)||"INSPECTOR".equals(value))return value;
        String mapped=properties.getLegacyRoleAccounts().get(user.getUsername());
        if("ADMIN".equals(value)&&"SUPERVISOR".equals(mapped))return mapped;
        if("OPERATOR".equals(value)&&"INSPECTOR".equals(mapped))return mapped;
        denied();return null;
    }
    private static void denied(){throw new DisabledException("账号未启用或不具备当前岗位登录资格");}
}
