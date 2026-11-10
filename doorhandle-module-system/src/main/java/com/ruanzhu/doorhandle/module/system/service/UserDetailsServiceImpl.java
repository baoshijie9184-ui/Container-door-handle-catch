package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.module.system.entity.User;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class UserDetailsServiceImpl implements UserDetailsService {
    private final UserMapper userMapper;
    private final LoginEligibilityService eligibility;
    private final com.ruanzhu.doorhandle.module.system.security.LoginSessionProperties properties;
    public UserDetailsServiceImpl(UserMapper users){this(users,null,null);}
    @Autowired public UserDetailsServiceImpl(UserMapper users,LoginEligibilityService eligibility,com.ruanzhu.doorhandle.module.system.security.LoginSessionProperties properties){this.userMapper=users;this.eligibility=eligibility;this.properties=properties;}

    @Override
    public UserDetails loadUserByUsername(String username) throws UsernameNotFoundException {
        User user = userMapper.findByUsername(username);
        if (user == null) {
            throw new UsernameNotFoundException("用户不存在");
        }
        
        String role = eligibility!=null?eligibility.requireCurrent(user.getId(),user.getUsername()).role():normalizeRole(user.getRole());
        return new TenantPrincipal(
            user.getId(),
            user.getUsername(),
            user.getPassword(),
            List.of(new SimpleGrantedAuthority("ROLE_" + role)),null,null,Boolean.TRUE.equals(user.getEnabled())
        );
    }

    private String normalizeRole(String value) {
        if ("SUPERVISOR".equals(value) || "INSPECTOR".equals(value)) return value;
        throw new UsernameNotFoundException("账号角色不具备登录资格");
    }
}
