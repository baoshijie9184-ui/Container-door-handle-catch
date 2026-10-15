package com.ruanzhu.doorhandle.module.system.api;
import com.ruanzhu.doorhandle.module.system.entity.User;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
class BusinessUserDirectoryImplTest {
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
