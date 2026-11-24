package com.ruanzhu.doorhandle.module.device.controller;

import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.entity.DeviceUsageRecord;
import com.ruanzhu.doorhandle.module.device.entity.Employee;
import org.springframework.beans.BeanUtils;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.List;

final class DirectoryResponses {
    private DirectoryResponses() {}

    static boolean includesContacts() {
        return isSupervisor();
    }

    private static boolean isSupervisor() {
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

    static Device visibleDevice(Device device) {
        return isSupervisor() ? device : employeeDevice(device);
    }

    static List<Device> visibleDevices(List<Device> devices) {
        return isSupervisor() ? devices : devices.stream().map(DirectoryResponses::employeeDevice).toList();
    }

    private static Device employeeDevice(Device device) {
        if (device == null) return null;
        // Publish inventory and connection status without copying the capture snapshot.
        var response = new Device();
        response.setId(device.getId());
        response.setVersion(device.getVersion());
        response.setDeviceCode(device.getDeviceCode());
        response.setDeviceType(device.getDeviceType());
        response.setModelName(device.getModelName());
        response.setSerialNumber(device.getSerialNumber());
        response.setStatus(device.getStatus());
        response.setOnlineStatus(device.getOnlineStatus());
        response.setLastHeartbeatAt(device.getLastHeartbeatAt());
        response.setLastMaintenanceDate(device.getLastMaintenanceDate());
        response.setEmployeeId(device.getEmployeeId());
        response.setEmployee(withoutContact(device.getEmployee()));
        response.setCreatedTime(device.getCreatedTime());
        response.setUpdatedTime(device.getUpdatedTime());
        return response;
    }

    static DeviceUsageRecord withoutContact(DeviceUsageRecord record) {
        if (record.getContact() == null) return record;
        var response = new DeviceUsageRecord();
        BeanUtils.copyProperties(record, response, "contact");
        return response;
    }
}
