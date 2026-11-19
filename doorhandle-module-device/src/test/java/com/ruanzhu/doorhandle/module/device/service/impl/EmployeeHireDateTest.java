package com.ruanzhu.doorhandle.module.device.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.organization.OrganizationDirectoryApi;
import com.ruanzhu.doorhandle.module.device.entity.Employee;
import com.ruanzhu.doorhandle.module.device.mapper.EmployeeMapper;
import org.apache.ibatis.session.Configuration;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.sql.ResultSet;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class EmployeeHireDateTest {
    private final EmployeeMapper mapper = mock(EmployeeMapper.class);
    private final OrganizationDirectoryApi organization = mock(OrganizationDirectoryApi.class);
    private final EmployeeServiceImpl service = spy(new EmployeeServiceImpl());

    @BeforeEach void setup() {
        ReflectionTestUtils.setField(service, "employeeMapper", mapper);
        ReflectionTestUtils.setField(service, "organization", organization);
        when(organization.requireDepartment(any(), any())).thenReturn(new OrganizationDirectoryApi.DepartmentIdentity(2L, "Department"));
        doReturn(true).when(service).save(any(Employee.class));
        doReturn(true).when(service).updateById(any(Employee.class));
    }

    @Test void mapperAndJsonRetainLegacyTextAndNormalCalendarDatesWithoutConversion() throws Exception {
        var json = new ObjectMapper();
        var handler = new Configuration().getTypeHandlerRegistry()
                .getTypeHandler(Employee.class.getDeclaredField("hireDate").getType());
        for (String value : new String[]{"2020-02-29", "2020年春", "待核对", " 2020-01-01 ", "", null}) {
            var row = mock(ResultSet.class);
            when(row.getString("hire_date")).thenReturn(value);
            Employee employee = new Employee();
            employee.setHireDate((String) handler.getResult(row, "hire_date"));
            assertThat(employee.getHireDate()).isEqualTo(value);
            assertThat(json.readValue(json.writeValueAsString(employee), Employee.class).getHireDate()).isEqualTo(value);
            verify(row).getString("hire_date");
        }
    }

    @Test void newCalendarDateRetainsExistingJsonValue() throws Exception {
        Employee employee = new ObjectMapper().readValue("{\"hireDate\":\"2020-02-29\"}", Employee.class);
        employee.setEmployeeType("DETECTION");
        employee.setEmployeeNumber("EMP-0011");
        assertThat(service.add(employee)).isTrue();
        assertThat(employee.getEmployeeNumber()).isEqualTo("DET-0011");
        assertThat(employee.getHireDate()).isEqualTo("2020-02-29");
        verify(service).save(employee);
    }

    @Test void newOrChangedInvalidCalendarDatesAreRejectedBeforeWriting() {
        for (String value : new String[]{"2021-02-29", "2020-2-01", "2020-01-01T00:00:00", "2020年春", "0000-01-01", " 2020-01-01 "}) {
            Employee employee = employee(value);
            assertThatThrownBy(() -> service.add(employee)).isInstanceOfSatisfying(BusinessException.class,
                    error -> assertThat(error.getCode()).isEqualTo(400));
        }
        verifyNoInteractions(mapper, organization);
        verify(service, never()).save(any(Employee.class));
        verify(service, never()).updateById(any(Employee.class));
    }

    @Test void unrelatedUpdatePreservesOriginalLegacyDateAndCanExplicitlyReplaceIt() {
        Employee original = employee("2020年春");
        when(mapper.selectById(11L)).thenReturn(original);
        Employee unchanged = employee("2020年春");
        unchanged.setName("New name");
        assertThat(service.update(unchanged)).isTrue();
        assertThat(unchanged.getHireDate()).isEqualTo("2020年春");
        verify(service).updateById(unchanged);

        Employee replacement = employee("2020-03-01");
        assertThat(service.update(replacement)).isTrue();
        assertThat(replacement.getHireDate()).isEqualTo("2020-03-01");
        verify(service).updateById(replacement);
    }

    @Test void legacyTextCannotBeIntroducedByChangingADifferentExistingValue() {
        when(mapper.selectById(11L)).thenReturn(employee("2020年春"));
        assertThatThrownBy(() -> service.update(employee("2021年春")))
                .isInstanceOfSatisfying(BusinessException.class, error -> assertThat(error.getCode()).isEqualTo(400));
        verify(service, never()).updateById(any(Employee.class));
        verifyNoInteractions(organization);
    }

    @Test void omittedAndEmptyDateKeepTheExistingPartialUpdateContract() {
        when(mapper.selectById(11L)).thenReturn(employee("2020年春"));
        for (String value : new String[]{null, ""}) {
            Employee update = employee(value);
            assertThat(service.update(update)).isTrue();
            assertThat(update.getHireDate()).isNull();
        }
        verify(service, times(2)).updateById(any(Employee.class));
    }

    @Test void roleChangeUsesTheExistingSerialAndPartialUpdatesKeepHistoricalNumbers() {
        var existing = employee(null);
        existing.setEmployeeNumber("EMP-0011");
        existing.setEmployeeType("DETECTION");
        when(mapper.selectById(11L)).thenReturn(existing);
        for (String[] role : new String[][] {{"SUPERVISOR","SUP"},{"COLLECTION","COL"},{"MAINTENANCE","MNT"}}) {
            var update = employee(null);
            update.setEmployeeType(role[0]);
            assertThat(service.update(update)).isTrue();
            assertThat(update.getEmployeeNumber()).isEqualTo(role[1] + "-0011");
        }
        var partial = employee(null);
        assertThat(service.update(partial)).isTrue();
        assertThat(partial.getEmployeeNumber()).isNull();
    }

    private Employee employee(String date) {
        Employee employee = new Employee();
        employee.setId(11L);
        employee.setVersion(0);
        employee.setHireDate(date);
        return employee;
    }
}
