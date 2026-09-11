package com.ruanzhu.doorhandle.module.device.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.entity.Employee;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceMapper;
import com.ruanzhu.doorhandle.module.device.service.EmployeeService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.security.access.prepost.PreAuthorize;

import java.util.List;

@RestController
@RequestMapping("/api")
public class EmployeeController {

    @Autowired
    private EmployeeService employeeService;

    @Autowired
    private DeviceMapper deviceMapper;

    @GetMapping("/employees")
    public Result<Page<Employee>> findByPage(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "10") int size,
            @RequestParam(required = false) String name,
            @RequestParam(required = false) String employeeNumber,
            @RequestParam(required = false) String contact,
            @RequestParam(required = false) String department,
            @RequestParam(required = false) String employeeType,
            @RequestParam(required = false) String status) {

        Page<Employee> pageResult = employeeService.findByPage(
                page, size, name, employeeNumber, contact, department, employeeType, status);
        return Result.success(pageResult);
    }

    @GetMapping("/employees/{id}")
    public Result<Employee> getById(@PathVariable Long id) {
        Employee employee = employeeService.getById(id);
        if (employee == null) {
            return Result.error("员工不存在");
        }
        if (!"ACTIVE".equals(employee.getStatus())) {
            return Result.error("休假或离职员工不能分配设备");
        }
        return Result.success(employee);
    }

    @GetMapping("/employees/check-number")
    public Result<Boolean> checkEmployeeNumber(
            @RequestParam String employeeNumber,
            @RequestParam(required = false) Long excludeId) {
        boolean exists = employeeService.existsByEmployeeNumber(employeeNumber, excludeId);
        return Result.success(exists);
    }

    @PostMapping("/employees")
    @PreAuthorize("hasRole('SUPERVISOR')")
    public Result<Employee> add(@RequestBody Employee employee) {
        boolean success = employeeService.add(employee);
        if (!success) {
            return Result.error("员工添加失败");
        }
        return Result.success(employee);
    }

    @PutMapping("/employees/{id}")
    @PreAuthorize("hasRole('SUPERVISOR')")
    public Result<Employee> update(@PathVariable Long id, @RequestBody Employee employee) {
        employee.setId(id);
        boolean success = employeeService.update(employee);
        if (!success) {
            return Result.error("员工更新失败");
        }
        return Result.success(employee);
    }

    @DeleteMapping("/employees/{id}")
    @PreAuthorize("hasRole('SUPERVISOR')")
    public Result<Boolean> delete(@PathVariable Long id) {
        boolean success = employeeService.delete(id);
        if (!success) {
            return Result.error("员工删除失败");
        }
        return Result.success(true);
    }

    @GetMapping("/employees/type/{employeeType}")
    public Result<List<Employee>> findByEmployeeType(@PathVariable String employeeType) {
        return Result.success(employeeService.findByEmployeeType(employeeType));
    }

    @GetMapping("/employees/{id}/devices")
    public Result<List<Device>> getDevicesByEmployeeId(@PathVariable Long id) {
        return Result.success(employeeService.getDevicesByEmployeeId(id));
    }

    @PostMapping("/employees/{employeeId}/assign-device/{deviceId}")
    @PreAuthorize("hasRole('SUPERVISOR')")
    public Result<Boolean> assignDeviceToEmployee(@PathVariable Long employeeId, @PathVariable Long deviceId) {
        Employee employee = employeeService.getById(employeeId);
        Device device = deviceMapper.selectById(deviceId);

        if (employee == null) {
            return Result.error("员工不存在");
        }
        if (device == null) {
            return Result.error("设备不存在");
        }

        String employeeType = employee.getEmployeeType();
        String deviceType = device.getDeviceType();

        if ("DETECTION".equals(deviceType)
                && !("DETECTION".equals(employeeType) || "MAINTENANCE".equals(employeeType))) {
            return Result.error("检测设备只能分配给检测人员或维修人员");
        }

        if ("IMAGE_CAPTURE".equals(deviceType)
                && !("COLLECTION".equals(employeeType) || "MAINTENANCE".equals(employeeType))) {
            return Result.error("采集设备只能分配给采集人员或维修人员");
        }

        boolean success = employeeService.assignDeviceToEmployee(employeeId, deviceId);
        if (!success) {
            return Result.error("设备分配失败");
        }
        return Result.success(true);
    }

    @GetMapping("/employees/stats")
    public Result<java.util.Map<String, Object>> getEmployeeStats() {
        try {
            return Result.success(employeeService.getEmployeeStats());
        } catch (Exception e) {
            return Result.error("获取员工统计失败: " + e.getMessage());
        }
    }
}
