package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.module.system.entity.User;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.core.GrantedAuthority;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class UserDetailsServiceImplTest {

    @Mock
    private UserMapper userMapper;

    @Test
    void mapsLegacyAdminRoleToSupervisor() {
        User user = user("admin", "ADMIN");
        when(userMapper.findByUsername("admin")).thenReturn(user);

        var details = new UserDetailsServiceImpl(userMapper).loadUserByUsername("admin");

        assertThat(details.getAuthorities())
                .extracting(GrantedAuthority::getAuthority)
                .containsExactly("ROLE_SUPERVISOR");
    }

    @Test
    void defaultsUnknownRoleToInspector() {
        User user = user("alice", "unexpected");
        when(userMapper.findByUsername("alice")).thenReturn(user);

        var details = new UserDetailsServiceImpl(userMapper).loadUserByUsername("alice");

        assertThat(details.getAuthorities())
                .extracting(GrantedAuthority::getAuthority)
                .containsExactly("ROLE_INSPECTOR");
    }

    private User user(String username, String role) {
        User user = new User();
        user.setUsername(username);
        user.setPassword("hash");
        user.setRole(role);
        return user;
    }
}
