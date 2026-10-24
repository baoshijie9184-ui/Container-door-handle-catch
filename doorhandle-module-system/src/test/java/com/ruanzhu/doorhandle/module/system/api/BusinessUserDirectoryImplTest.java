package com.ruanzhu.doorhandle.module.system.api;
import com.ruanzhu.doorhandle.module.system.entity.User;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
class BusinessUserDirectoryImplTest {
    @Test void identityBackfillRequiresAnExactUniqueAccount(){
        var mapper=mock(UserMapper.class);var directory=new BusinessUserDirectoryImpl(mapper);
        var exact=new User();exact.setId(1L);exact.setUsername("alice");var folded=new User();folded.setId(2L);folded.setUsername("Alice");
        when(mapper.selectList(any(com.baomidou.mybatisplus.core.conditions.Wrapper.class))).thenReturn(java.util.List.of(folded));
        assertThat(directory.findExactUserId("alice")).isNull();
        when(mapper.selectList(any(com.baomidou.mybatisplus.core.conditions.Wrapper.class))).thenReturn(java.util.List.of(exact,folded));
        assertThat(directory.findExactUserId("alice")).isEqualTo(1);
        var duplicate=new User();duplicate.setId(3L);duplicate.setUsername("alice");
        when(mapper.selectList(any(com.baomidou.mybatisplus.core.conditions.Wrapper.class))).thenReturn(java.util.List.of(exact,duplicate));
        assertThat(directory.findExactUserId("alice")).isNull();
    }
    @Test void revokedOrUnknownRoleDoesNotFallBackToInspector(){
        var mapper=mock(UserMapper.class);var directory=new BusinessUserDirectoryImpl(mapper);var user=new User();user.setUsername("alice");when(mapper.selectById(1L)).thenReturn(user);
        for(String role:new String[]{null,"USER","DISABLED","UNKNOWN"}){user.setRole(role);assertThatThrownBy(()->directory.current(1,"alice")).isInstanceOf(SecurityException.class);}
    }
    @Test void legacyRoleAliasesRemainCompatible(){
        var mapper=mock(UserMapper.class);var directory=new BusinessUserDirectoryImpl(mapper);var user=new User();user.setUsername("alice");when(mapper.selectById(1L)).thenReturn(user);
        user.setRole("ADMIN");assertThat(directory.current(1,"alice").supervisor()).isTrue();user.setRole("OPERATOR");assertThat(directory.current(1,"alice").supervisor()).isFalse();
    }
    @Test void freshDatabaseRoleOverridesPreviouslyGrantedRole(){
        var mapper=mock(UserMapper.class);var directory=new BusinessUserDirectoryImpl(mapper);
        var user=new User();user.setUsername("boss");user.setRole("SUPERVISOR");when(mapper.selectById(3L)).thenReturn(user);
        assertThat(directory.current(3,"boss").supervisor()).isTrue();user.setRole("INSPECTOR");
        assertThat(directory.current(3,"boss").supervisor()).isFalse();
    }
    @Test void missingOrMismatchedIdentityIsRejected(){
        var mapper=mock(UserMapper.class);var directory=new BusinessUserDirectoryImpl(mapper);
        assertThatThrownBy(()->directory.current(1,"alice")).isInstanceOf(SecurityException.class);
        var user=new User();user.setUsername("other");when(mapper.selectById(1L)).thenReturn(user);
        assertThatThrownBy(()->directory.current(1,"alice")).isInstanceOf(SecurityException.class);
    }
}
