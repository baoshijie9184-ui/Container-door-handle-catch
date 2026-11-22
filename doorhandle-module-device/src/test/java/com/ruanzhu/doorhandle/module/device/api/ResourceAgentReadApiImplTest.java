package com.ruanzhu.doorhandle.module.device.api;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.ruanzhu.doorhandle.module.device.entity.Employee;
import java.util.ArrayList;
import java.util.List;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceMapper;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceCaptureAlertMapper;
import com.ruanzhu.doorhandle.module.device.service.EmployeeService;
import com.ruanzhu.doorhandle.contracts.agent.ResourceAgentReadApi.EmployeeCounts;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class ResourceAgentReadApiImplTest {
    final DeviceMapper mapper=mock(DeviceMapper.class);
    final DeviceCaptureAlertMapper alerts=mock(DeviceCaptureAlertMapper.class);
    final EmployeeService employees = mock(EmployeeService.class);
    final BusinessUserDirectory accounts = mock(BusinessUserDirectory.class);
    final ResourceAgentReadApiImpl api=new ResourceAgentReadApiImpl(mapper,alerts,employees,accounts);
    final AgentActor boss=new AgentActor(1,"boss",AgentActor.Role.SUPERVISOR);

    @BeforeEach void currentAccounts() {
        when(accounts.current(1, "boss")).thenReturn(new BusinessUserDirectory.Identity(1, "boss", true));
        when(accounts.current(2, "staff")).thenReturn(new BusinessUserDirectory.Identity(2, "staff", false));
    }

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
        second.setGender("excluded-gender"); second.setDepartmentId(49L);
        when(employees.page(org.mockito.ArgumentMatchers.<Page<Employee>>any(), any())).thenAnswer(call -> {
            Page<Employee> page = call.getArgument(0);
            QueryWrapper<Employee> query = call.getArgument(1);
            assertThat(query.getSqlSegment()).contains("name =", "ORDER BY id ASC").doesNotContain("LIKE");
            assertThat(query.getSqlSelect().split(",")).containsExactlyInAnyOrder(
                    "name", "employee_number", "department", "employee_type", "status", "hire_date");
            assertThat(query.getParamNameValuePairs()).containsValue("张三");
            return page.setTotal(2).setRecords(List.of(first, second));
        });
        for (var actor : List.of(boss, new AgentActor(2, "staff", AgentActor.Role.INSPECTOR))) {
            var result = api.employeesByName(actor, " 张三 ", 1);
            assertThat(result.total()).isEqualTo(2);
            assertThat(result.records()).extracting("employeeNumber").containsExactly("A1", "B2");
            var json = new ObjectMapper().readTree(new ObjectMapper().writeValueAsString(result));
            for (var record : json.path("records")) {
                var fields = new ArrayList<String>();
                record.fieldNames().forEachRemaining(fields::add);
                assertThat(fields).containsExactlyInAnyOrder(
                        "name", "employeeNumber", "department", "employeeType", "status", "hireDate");
            }
            assertThat(json.toString()).doesNotContain("excluded-contact", "excluded-remark", "excluded-gender");
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
        when(mapper.selectOne(any())).thenReturn(device);
        var result=api.device(boss,Long.MAX_VALUE);
        assertThat(result.deviceId()).isEqualTo("9223372036854775807");
        assertThat(new ObjectMapper().writeValueAsString(result)).contains("CODE-DIFFERENT","OFFLINE").doesNotContain("private-serial","serialNumber","employee");
        var query = ArgumentCaptor.forClass(QueryWrapper.class);
        verify(mapper).selectOne(query.capture());
        assertThat(query.getValue().getSqlSelect().split(",")).containsExactlyInAnyOrder(
                "id", "device_code", "status", "online_status", "plc_status", "camera_status", "capture_status");
        assertThat(query.getValue().getSqlSegment()).contains("id =");
        assertThat(query.getValue().getParamNameValuePairs()).containsValue(Long.MAX_VALUE);
        when(mapper.selectOne(any())).thenReturn(null);
        assertThatThrownBy(()->api.device(boss,Long.MAX_VALUE)).isInstanceOfSatisfying(BusinessException.class,e->assertThat(e.getCode()).isEqualTo(404));
    }
    @Test void inspectorCannotReadEitherResourcePathAndInvalidIdsNeverReachStorage(){
        var staff=new AgentActor(2,"staff",AgentActor.Role.INSPECTOR);
        assertThatThrownBy(()->api.device(staff,1)).isInstanceOf(SecurityException.class);
        assertThatThrownBy(()->api.devices(staff,1,10)).isInstanceOf(SecurityException.class);
        assertThatThrownBy(()->api.device(boss,0)).isInstanceOf(IllegalArgumentException.class);
        verifyNoInteractions(mapper);
    }

    @Test void roleRevocationAndAccountDisablementAreCheckedBeforeReadingStorage() {
        when(accounts.current(1, "boss")).thenReturn(new BusinessUserDirectory.Identity(1, "boss", false));
        assertThatThrownBy(() -> api.device(boss, 1)).isInstanceOf(SecurityException.class);
        assertThatThrownBy(() -> api.devices(boss, 1, 10)).isInstanceOf(SecurityException.class);
        assertThatThrownBy(() -> api.alert(boss, 1)).isInstanceOf(SecurityException.class);

        var staff = new AgentActor(2, "staff", AgentActor.Role.INSPECTOR);
        when(accounts.current(2, "staff")).thenThrow(new SecurityException("disabled"));
        assertThatThrownBy(() -> api.employeesByName(staff, "张三", 1)).isInstanceOf(SecurityException.class);
        assertThatThrownBy(() -> api.employeeCounts(staff)).isInstanceOf(SecurityException.class);
        verifyNoInteractions(mapper, alerts, employees);
    }
}
