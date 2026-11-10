package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.organization.EmployeeDirectoryApi;
import com.ruanzhu.doorhandle.module.system.entity.*;
import com.ruanzhu.doorhandle.module.system.mapper.*;
import com.ruanzhu.doorhandle.module.system.security.LoginSessionProperties;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.security.authentication.DisabledException;
import java.util.*;
import static org.mockito.Mockito.*;
import static org.assertj.core.api.Assertions.*;

class LoginEligibilityServiceTest {
    final UserMapper users=mock(UserMapper.class);
    final AccountEmployeeBindingMapper bindings=mock(AccountEmployeeBindingMapper.class);
    final EmployeeDirectoryApi employees=mock(EmployeeDirectoryApi.class);
    final LoginSessionProperties properties=new LoginSessionProperties();
    final LoginEligibilityService service=new LoginEligibilityService(users,bindings,employees,properties);
    User account(String role){var user=new User();user.setId(7L);user.setUsername("member");user.setRole(role);when(users.selectById(7L)).thenReturn(user);return user;}
    void staff(String type,String status){var binding=new AccountEmployeeBinding();binding.setUserId(7L);binding.setEmployeeId(10L);when(bindings.selectById(7L)).thenReturn(binding);
        when(employees.findAll(List.of(10L))).thenReturn(List.of(new EmployeeDirectoryApi.EmployeeIdentity(10L,"E10","Member",status,type,1L,"Team")));}
    @Test void supervisorMayBootstrapWithoutAPersonnelBinding(){account("SUPERVISOR");assertThat(service.requireCurrent(7,"member").role()).isEqualTo("SUPERVISOR");}
    @Test void inspectorRequiresAnActiveDetectionPosition(){account("INSPECTOR");assertThatThrownBy(()->service.requireCurrent(7,"member")).isInstanceOf(DisabledException.class);staff("DETECTION","ACTIVE");assertThat(service.requireCurrent(7,"member").role()).isEqualTo("INSPECTOR");}
    @ParameterizedTest @ValueSource(strings={"COLLECTION","MAINTENANCE","unexpected"}) void nonLoginPositionsCannotAcquireSupervisorAccess(String position){account("SUPERVISOR");staff(position,"ACTIVE");assertThatThrownBy(()->service.requireCurrent(7,"member")).isInstanceOf(DisabledException.class);}
    @Test void disabledOrResignedAccountsAreRejectedFromCurrentFacts(){var user=account("INSPECTOR");staff("DETECTION","ACTIVE");user.setEnabled(false);assertThatThrownBy(()->service.requireCurrent(7,"member")).isInstanceOf(DisabledException.class);user.setEnabled(true);staff("DETECTION","RESIGNED");assertThatThrownBy(()->service.requireCurrent(7,"member")).isInstanceOf(DisabledException.class);}
    @Test void legacyAliasesRequireAnExplicitPerAccountRoleDecision(){account("ADMIN");assertThatThrownBy(()->service.requireCurrent(7,"member")).isInstanceOf(DisabledException.class);properties.setLegacyRoleAccounts(Map.of("member","SUPERVISOR"));assertThat(service.requireCurrent(7,"member").role()).isEqualTo("SUPERVISOR");}
    @Test void unknownRoleAndIdentityMismatchFailClosed(){account("unexpected");assertThatThrownBy(()->service.requireCurrent(7,"member")).isInstanceOf(DisabledException.class);assertThatThrownBy(()->service.requireCurrent(7,"someone-else")).isInstanceOf(DisabledException.class);}
    @Test void lockedEligibilityUsesCurrentBindingAndLocksActualPersonnelInsteadOfAnOldSnapshot(){
        var user=account("INSPECTOR");when(users.selectOne(any(com.baomidou.mybatisplus.core.conditions.Wrapper.class))).thenReturn(user);
        var binding=new AccountEmployeeBinding();binding.setUserId(7L);binding.setEmployeeId(12L);when(bindings.selectLockedById(7L)).thenReturn(binding);
        when(employees.lock(12L)).thenReturn(new EmployeeDirectoryApi.EmployeeIdentity(12L,"E12","Current Staff","ACTIVE","DETECTION",1L,"Team"));
        assertThat(service.lockCurrent(7,"member").role()).isEqualTo("INSPECTOR");
        verify(bindings,never()).selectById(any());verify(employees,never()).findAll(any());verify(employees).lock(12L);
    }
    @Test void mutationLockRejectsPersonnelThatBecameInactiveBeforeTheLockWasObtained(){
        var user=account("INSPECTOR");when(users.selectOne(any(com.baomidou.mybatisplus.core.conditions.Wrapper.class))).thenReturn(user);
        var binding=new AccountEmployeeBinding();binding.setUserId(7L);binding.setEmployeeId(12L);when(bindings.selectLockedById(7L)).thenReturn(binding);
        when(employees.lock(12L)).thenReturn(new EmployeeDirectoryApi.EmployeeIdentity(12L,"E12","Former Staff","RESIGNED","DETECTION",1L,"Team"));
        assertThatThrownBy(()->service.lockCurrent(7,"member")).isInstanceOf(DisabledException.class);
    }
}
