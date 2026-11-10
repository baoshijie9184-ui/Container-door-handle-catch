package com.ruanzhu.doorhandle.module.system.api;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.module.system.entity.User;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
class AgentUserDirectoryImplTest {
    @Test void rereadsCurrentDatabaseRoleAndRejectsMissingOrMismatchedIdentity() {
        var users=mock(UserMapper.class);var directory=new AgentUserDirectoryImpl(users);
        var actor=new AgentActor(1,"boss",AgentActor.Role.SUPERVISOR);
        var user=new User();user.setId(1L);user.setUsername("boss");user.setRole("SUPERVISOR");when(users.selectOne(any(com.baomidou.mybatisplus.core.conditions.Wrapper.class))).thenReturn(user);
        assertThatCode(()->directory.assertSupervisor(actor)).doesNotThrowAnyException();
        user.setRole("INSPECTOR");assertThatThrownBy(()->directory.assertSupervisor(actor)).isInstanceOf(SecurityException.class);
        user.setRole("SUPERVISOR");user.setUsername("other");assertThatThrownBy(()->directory.assertSupervisor(actor)).isInstanceOf(SecurityException.class);
        when(users.selectOne(any(com.baomidou.mybatisplus.core.conditions.Wrapper.class))).thenReturn(null);assertThatThrownBy(()->directory.assertSupervisor(actor)).isInstanceOf(SecurityException.class);
    }
    @Test void assignmentTargetsMustBeActualInspectorAccounts() {
        var users=mock(UserMapper.class);var directory=new AgentUserDirectoryImpl(users);
        assertThat(directory.inspectorExists("missing")).isFalse();var user=new User();user.setId(2L);user.setUsername("account");user.setRole("SUPERVISOR");when(users.selectList(any(com.baomidou.mybatisplus.core.conditions.Wrapper.class))).thenReturn(java.util.List.of(user));
        assertThat(directory.inspectorExists("account")).isFalse();user.setRole("INSPECTOR");assertThat(directory.inspectorExists("account")).isTrue();
    }
    @Test void collaborationCandidateSelectionRejectsAnInspectorWhosePersonnelEligibilityWasRevoked(){
        var mapper=mock(UserMapper.class);var directory=new AgentUserDirectoryImpl(mapper);
        var eligibility=mock(com.ruanzhu.doorhandle.module.system.service.LoginEligibilityService.class);
        var properties=new com.ruanzhu.doorhandle.module.system.security.LoginSessionProperties();properties.setEnabled(true);directory.eligibility(eligibility,properties);
        var user=new User();user.setId(2L);user.setUsername("account");user.setRole("INSPECTOR");
        when(mapper.selectList(any(com.baomidou.mybatisplus.core.conditions.Wrapper.class))).thenReturn(java.util.List.of(user));
        when(eligibility.requireCurrent(2,"account")).thenThrow(new org.springframework.security.authentication.DisabledException("staff left"));
        assertThat(directory.inspectorExists("account")).isFalse();
        assertThatThrownBy(()->directory.inspector("account")).isInstanceOf(SecurityException.class);
    }
    @Test void supervisorChecksUseTheEligibleRoleAndLegacyAliasesRequireExplicitMapping(){
        var mapper=mock(UserMapper.class);var directory=new AgentUserDirectoryImpl(mapper);
        var eligibility=mock(com.ruanzhu.doorhandle.module.system.service.LoginEligibilityService.class);
        var properties=new com.ruanzhu.doorhandle.module.system.security.LoginSessionProperties();properties.setEnabled(true);directory.eligibility(eligibility,properties);
        var user=new User();user.setId(1L);user.setUsername("boss");user.setRole("ADMIN");when(mapper.selectOne(any(com.baomidou.mybatisplus.core.conditions.Wrapper.class))).thenReturn(user);
        when(eligibility.requireCurrent(1,"boss")).thenReturn(new com.ruanzhu.doorhandle.module.system.service.LoginEligibilityService.Eligible(user,"SUPERVISOR"));
        var actor=new AgentActor(1,"boss",AgentActor.Role.SUPERVISOR);assertThatCode(()->directory.assertSupervisor(actor)).doesNotThrowAnyException();
        when(eligibility.requireCurrent(1,"boss")).thenThrow(new org.springframework.security.authentication.DisabledException("alias not mapped"));
        assertThatThrownBy(()->directory.assertSupervisor(actor)).isInstanceOf(SecurityException.class);
    }
}
