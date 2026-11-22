package com.ruanzhu.doorhandle.module.device.controller;

import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.entity.DeviceUsageRecord;
import com.ruanzhu.doorhandle.module.device.entity.Employee;
import org.springframework.beans.BeanUtils;
import org.springframework.security.core.context.SecurityContextHolder;

final class DirectoryResponses {
    private DirectoryResponses() {}

    static boolean includesContacts() {
        var authentication = SecurityContextHolder.getContext().getAuthentication();
        return authentication != null && authentication.isAuthenticated() && authentication.getAuthorities().stream()
                .anyMatch(authority -> "ROLE_SUPERVISOR".equals(authority.getAuthority()));
    }

    static Employee withoutContact(Employee employee) {
        if (employee == null || employee.getContact() == null) return employee;
        var response = new Employee();
        BeanUtils.copyProperties(employee, response, "contact");
        return response;
    }

    static Device withoutContact(Device device) {
        if (device == null || device.getEmployee() == null || device.getEmployee().getContact() == null) return device;
        var response = new Device();
        BeanUtils.copyProperties(device, response, "employee");
        response.setEmployee(withoutContact(device.getEmployee()));
        return response;
    }

    static DeviceUsageRecord withoutContact(DeviceUsageRecord record) {
        if (record.getContact() == null) return record;
        var response = new DeviceUsageRecord();
        BeanUtils.copyProperties(record, response, "contact");
        return response;
    }
}
