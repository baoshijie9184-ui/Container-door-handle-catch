package com.ruanzhu.doorhandle.module.device.service;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.module.system.api.BusinessUserDirectoryImpl;
import com.ruanzhu.doorhandle.module.system.entity.User;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Actual account directory role refresh and device existence policy; execute in the ECS source suite. */
class DeviceMutationParticipantReadTest {
    JdbcTemplate jdbc;UserMapper accounts;User current;DeviceMutationParticipant participant;
    final AgentActor staleSupervisor=new AgentActor(1,"alice",AgentActor.Role.SUPERVISOR);
    @BeforeEach void setup(){
        jdbc=mock(JdbcTemplate.class);accounts=mock(UserMapper.class);current=new User();current.setId(1L);current.setUsername("alice");current.setRole("INSPECTOR");
        when(accounts.selectOne(any(com.baomidou.mybatisplus.core.conditions.Wrapper.class))).thenReturn(current);
        participant=new DeviceMutationParticipant(jdbc,new BusinessUserDirectoryImpl(accounts));
    }
    @Test void qualifiedInspectorCanReadAnExistingDeviceThroughTheActualDirectory(){
        when(jdbc.queryForObject(anyString(),eq(Boolean.class),eq(41L))).thenReturn(true);
        assertThat(participant.mayRead(staleSupervisor,"ENTERPRISE","DEVICE","DEVICE","41")).isTrue();
        assertThat(participant.mayRead(staleSupervisor,"ENTERPRISE","EMPLOYEE","EMPLOYEE","41")).isFalse();
    }
    @Test void onlyCurrentSupervisorCanReadADeletedDevicesHistory(){
        when(jdbc.queryForObject(anyString(),eq(Boolean.class),eq(41L))).thenReturn(false);
        assertThat(participant.mayRead(staleSupervisor,"ENTERPRISE","DEVICE","DEVICE","41")).isFalse();
        current.setRole("SUPERVISOR");
        assertThat(participant.mayRead(new AgentActor(1,"alice",AgentActor.Role.INSPECTOR),"ENTERPRISE","DEVICE","DEVICE","41")).isTrue();
        assertThat(participant.mayRead(staleSupervisor,"ENTERPRISE","DEVICE","DEVICE","9223372036854775808")).isFalse();
    }
    @Test void sensitiveAndUnknownResourcesStayDeniedAndReadAccessDoesNotGrantWrites(){
        when(jdbc.queryForObject(anyString(),eq(Boolean.class),eq(41L))).thenReturn(true);
        for(String type:new String[]{"EMPLOYEE","DEVICE_USAGE","DEVICE_ALERT","UNKNOWN"})
            assertThat(participant.mayRead(staleSupervisor,"ENTERPRISE",type,type,"41")).isFalse();
        assertThat(participant.mayRead(staleSupervisor,"PRIVATE","DEVICE","DEVICE","41")).isFalse();
        assertThat(participant.mayRead(staleSupervisor,"ENTERPRISE","EMPLOYEE","DEVICE","41")).isFalse();
        assertThatThrownBy(()->participant.capture(staleSupervisor,"DEVICE","updateDevice","41",true)).isInstanceOf(SecurityException.class);
    }
    @Test void unknownOrMissingCurrentAccountCannotReadDeviceHistory(){
        current.setRole("UNKNOWN");assertThat(participant.mayRead(staleSupervisor,"ENTERPRISE","DEVICE","DEVICE","41")).isFalse();
        when(accounts.selectOne(any(com.baomidou.mybatisplus.core.conditions.Wrapper.class))).thenReturn(null);
        assertThat(participant.mayRead(staleSupervisor,"ENTERPRISE","DEVICE","DEVICE","41")).isFalse();
        verifyNoInteractions(jdbc);
    }
}
