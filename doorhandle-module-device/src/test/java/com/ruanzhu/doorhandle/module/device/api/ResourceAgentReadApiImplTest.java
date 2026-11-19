package com.ruanzhu.doorhandle.module.device.api;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceMapper;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceCaptureAlertMapper;
import com.ruanzhu.doorhandle.module.device.service.EmployeeService;
import com.ruanzhu.doorhandle.contracts.agent.ResourceAgentReadApi.EmployeeCounts;
import java.util.Map;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class ResourceAgentReadApiImplTest {
    final DeviceMapper mapper=mock(DeviceMapper.class);
    final EmployeeService employees = mock(EmployeeService.class);
    final ResourceAgentReadApiImpl api=new ResourceAgentReadApiImpl(mapper,mock(DeviceCaptureAlertMapper.class),employees);
    final AgentActor boss=new AgentActor(1,"boss",AgentActor.Role.SUPERVISOR);

    @Test void rosterUsesOnlyDashboardCountsForBothAuthenticatedRoles() {
        when(employees.getEmployeeStats()).thenReturn(Map.of("total", 9L, "active", 7, "vacation", 0, "resigned", 2, "ignored", "private"));
        for (var actor : java.util.List.of(boss, new AgentActor(2, "staff", AgentActor.Role.INSPECTOR))) {
            assertThat(api.employeeCounts(actor)).isEqualTo(new EmployeeCounts(9, 7, 0, 2));
        }
        when(employees.getEmployeeStats()).thenReturn(Map.of("total", 9L));
        assertThatThrownBy(() -> api.employeeCounts(boss)).isInstanceOf(IllegalStateException.class);
    }
    @Test void detailRetainsExactPrimaryKeyAndOnlyReturnsOperationalSummary() throws Exception {
        var device=new Device();device.setId(Long.MAX_VALUE);device.setDeviceCode("CODE-DIFFERENT");
        device.setStatus("IDLE");device.setOnlineStatus("OFFLINE");device.setSerialNumber("private-serial");
        when(mapper.selectById(Long.MAX_VALUE)).thenReturn(device);
        var result=api.device(boss,Long.MAX_VALUE);
        assertThat(result.deviceId()).isEqualTo("9223372036854775807");
        assertThat(new ObjectMapper().writeValueAsString(result)).contains("CODE-DIFFERENT","OFFLINE").doesNotContain("private-serial","serialNumber","employee");
        when(mapper.selectById(Long.MAX_VALUE)).thenReturn(null);
        assertThatThrownBy(()->api.device(boss,Long.MAX_VALUE)).isInstanceOfSatisfying(BusinessException.class,e->assertThat(e.getCode()).isEqualTo(404));
    }
    @Test void inspectorCannotReadEitherResourcePathAndInvalidIdsNeverReachStorage(){
        var staff=new AgentActor(2,"staff",AgentActor.Role.INSPECTOR);
        assertThatThrownBy(()->api.device(staff,1)).isInstanceOf(SecurityException.class);
        assertThatThrownBy(()->api.devices(staff,1,10)).isInstanceOf(SecurityException.class);
        assertThatThrownBy(()->api.device(boss,0)).isInstanceOf(IllegalArgumentException.class);
        verifyNoInteractions(mapper);
    }
}
