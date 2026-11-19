package com.ruanzhu.doorhandle.module.device.api;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.ruanzhu.doorhandle.module.device.entity.Employee;
import java.util.List;
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
    @Test void exactNameReturnsDistinctRecordsAndOnlyTheDirectorySummary() throws Exception {
        var first = new Employee(); first.setName("张三"); first.setEmployeeNumber("A1"); first.setContact("excluded-contact");
        var second = new Employee(); second.setName("张三"); second.setEmployeeNumber("B2"); second.setRemark("excluded-remark");
        when(employees.page(org.mockito.ArgumentMatchers.<Page<Employee>>any(), any())).thenAnswer(call -> {
            Page<Employee> page = call.getArgument(0);
            QueryWrapper<Employee> query = call.getArgument(1);
            assertThat(query.getSqlSegment()).contains("name =", "ORDER BY id ASC").doesNotContain("LIKE");
            assertThat(query.getSqlSelect()).doesNotContain("contact", "remark");
            assertThat(query.getParamNameValuePairs()).containsValue("张三");
            return page.setTotal(2).setRecords(List.of(first, second));
        });
        for (var actor : List.of(boss, new AgentActor(2, "staff", AgentActor.Role.INSPECTOR))) {
            var result = api.employeesByName(actor, " 张三 ", 1);
            assertThat(result.total()).isEqualTo(2);
            assertThat(result.records()).extracting("employeeNumber").containsExactly("A1", "B2");
            assertThat(new ObjectMapper().writeValueAsString(result)).doesNotContain("contact", "remark");
        }
    }

    @Test void emptyResultAndInvalidNameAreDistinct() {
        when(employees.page(org.mockito.ArgumentMatchers.<Page<Employee>>any(), any())).thenReturn(new Page<Employee>(1, 10));
        assertThat(api.employeesByName(boss, "无人匹配", 1).records()).isEmpty();
        clearInvocations(employees);
        for (var name : List.of("", "  ", "长".repeat(51))) {
            assertThatThrownBy(() -> api.employeesByName(boss, name, 1)).isInstanceOf(IllegalArgumentException.class);
        }
        assertThatThrownBy(() -> api.employeesByName(boss, "张三", 0)).isInstanceOf(IllegalArgumentException.class);
        verifyNoInteractions(employees);
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
