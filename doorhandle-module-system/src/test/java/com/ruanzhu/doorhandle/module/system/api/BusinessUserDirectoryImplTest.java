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
        var mapper=mock(UserMapper.class);var directory=new BusinessUserDirectoryImpl(mapper);var user=new User();user.setUsername("alice");when(mapper.selectOne(any(com.baomidou.mybatisplus.core.conditions.Wrapper.class))).thenReturn(user);
        for(String role:new String[]{null,"USER","DISABLED","UNKNOWN"}){user.setRole(role);assertThatThrownBy(()->directory.current(1,"alice")).isInstanceOf(SecurityException.class);}
    }
    @Test void legacyRoleAliasesRemainCompatible(){
        var mapper=mock(UserMapper.class);var directory=new BusinessUserDirectoryImpl(mapper);var user=new User();user.setUsername("alice");when(mapper.selectOne(any(com.baomidou.mybatisplus.core.conditions.Wrapper.class))).thenReturn(user);
        user.setRole("ADMIN");assertThat(directory.current(1,"alice").supervisor()).isTrue();user.setRole("OPERATOR");assertThat(directory.current(1,"alice").supervisor()).isFalse();
    }
    @Test void freshDatabaseRoleOverridesPreviouslyGrantedRole(){
        var mapper=mock(UserMapper.class);var directory=new BusinessUserDirectoryImpl(mapper);
        var user=new User();user.setUsername("boss");user.setRole("SUPERVISOR");when(mapper.selectOne(any(com.baomidou.mybatisplus.core.conditions.Wrapper.class))).thenReturn(user);
        assertThat(directory.current(3,"boss").supervisor()).isTrue();user.setRole("INSPECTOR");
        assertThat(directory.current(3,"boss").supervisor()).isFalse();
    }
    @Test void missingOrMismatchedIdentityIsRejected(){
        var mapper=mock(UserMapper.class);var directory=new BusinessUserDirectoryImpl(mapper);
        assertThatThrownBy(()->directory.current(1,"alice")).isInstanceOf(SecurityException.class);
        var user=new User();user.setUsername("other");when(mapper.selectOne(any(com.baomidou.mybatisplus.core.conditions.Wrapper.class))).thenReturn(user);
        assertThatThrownBy(()->directory.current(1,"alice")).isInstanceOf(SecurityException.class);
    }
    @Test void enabledCollaborationUsesFreshPersonnelEligibilityInsteadOfLegacyRoleFallback(){
        var mapper=mock(UserMapper.class);var directory=new BusinessUserDirectoryImpl(mapper);
        var eligibility=mock(com.ruanzhu.doorhandle.module.system.service.LoginEligibilityService.class);
        var properties=new com.ruanzhu.doorhandle.module.system.security.LoginSessionProperties();properties.setEnabled(true);directory.eligibility(eligibility,properties);
        var user=new User();user.setId(3L);user.setUsername("boss");user.setRole("SUPERVISOR");
        when(eligibility.requireCurrent(3,"boss")).thenReturn(new com.ruanzhu.doorhandle.module.system.service.LoginEligibilityService.Eligible(user,"INSPECTOR"));
        assertThat(directory.current(3,"boss").supervisor()).isFalse();
        when(eligibility.requireCurrent(3,"boss")).thenThrow(new org.springframework.security.authentication.DisabledException("staff became ineligible"));
        assertThatThrownBy(()->directory.current(3,"boss")).isInstanceOf(SecurityException.class);
        verifyNoInteractions(mapper);
    }
    @Test void mutationIdentityLocksEligibilityAndCannotKeepUsingADisabledAccount(){
        var mapper=mock(UserMapper.class);var directory=new BusinessUserDirectoryImpl(mapper);
        var eligibility=mock(com.ruanzhu.doorhandle.module.system.service.LoginEligibilityService.class);
        var properties=new com.ruanzhu.doorhandle.module.system.security.LoginSessionProperties();properties.setEnabled(true);directory.eligibility(eligibility,properties);
        var user=new User();user.setId(3L);user.setUsername("boss");
        when(eligibility.lockCurrent(3,"boss")).thenReturn(new com.ruanzhu.doorhandle.module.system.service.LoginEligibilityService.Eligible(user,"SUPERVISOR"));
        assertThat(directory.lockCurrent(3,"boss").supervisor()).isTrue();
        when(eligibility.lockCurrent(3,"boss")).thenThrow(new org.springframework.security.authentication.DisabledException("account disabled"));
        assertThatThrownBy(()->directory.lockCurrent(3,"boss")).isInstanceOf(SecurityException.class);
        verify(eligibility,times(2)).lockCurrent(3,"boss");verifyNoInteractions(mapper);
    }
}
