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
}
