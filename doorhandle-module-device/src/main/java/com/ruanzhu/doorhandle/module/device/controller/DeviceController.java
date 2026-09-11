package com.ruanzhu.doorhandle.module.device.controller;

import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.device.dto.device.DeviceAlertActionRequest;
import com.ruanzhu.doorhandle.module.device.dto.device.DeviceHeartbeatRequest;
import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.entity.DeviceCaptureAlert;
import com.ruanzhu.doorhandle.module.device.entity.Employee;
import com.ruanzhu.doorhandle.module.device.service.DeviceService;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import lombok.RequiredArgsConstructor;
import org.springframework.validation.annotation.Validated;
import io.swagger.v3.oas.annotations.tags.Tag;
import io.swagger.v3.oas.annotations.Operation;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
@Validated
@Tag(name = "设备管理", description = "设备查询、维护、分配及采集告警接口")
public class DeviceController {

    private final DeviceService deviceService;

    @GetMapping("/devices")
    @Operation(summary = "分页查询设备")
    public Result<Map<String, Object>> getAllDevices(
            @RequestParam(required = false) String deviceCode,
            @RequestParam(required = false) String deviceType,
            @RequestParam(required = false) String modelName,
            @RequestParam(required = false) String serialNumber,
            @RequestParam(required = false) String status,
            @RequestParam(defaultValue = "1") Integer page,
            @RequestParam(defaultValue = "10") Integer size) {

        Map<String, Object> result = deviceService.getDevicesByPage(
                deviceCode, deviceType, modelName, serialNumber, status, page, size);
        return Result.success(result);
    }

    @GetMapping("/devices/unassigned")
    @Operation(summary = "查询未分配设备")
    public Result<List<Device>> getUnassignedDevices() {
        return Result.success(deviceService.getUnassignedDevices());
    }

    @GetMapping("/devices/{id}")
    @Operation(summary = "查询设备详情")
    public Result<Device> getDeviceById(@PathVariable Long id) {
        Device device = deviceService.getDeviceById(id);
        if (device == null) {
            return Result.error("设备不存在");
        }
        return Result.success(device);
    }

    @GetMapping("/devices/check-code")
    @Operation(summary = "检查设备编号")
    public Result<Boolean> checkDeviceCode(
            @RequestParam String deviceCode,
            @RequestParam(required = false) Long excludeId) {
        boolean exists = deviceService.existsByDeviceCode(deviceCode, excludeId);
        return Result.success(exists);
    }

    @PostMapping("/devices")
    @org.springframework.security.access.prepost.PreAuthorize("hasRole('SUPERVISOR')")
    @Operation(summary = "创建设备")
    public Result<Device> createDevice(@RequestBody Device device) {
        try {
            return Result.success(deviceService.createDevice(device));
        } catch (Exception e) {
            return Result.error("创建设备失败: " + e.getMessage());
        }
    }

    @PutMapping("/devices/{id}")
    @org.springframework.security.access.prepost.PreAuthorize("hasRole('SUPERVISOR')")
    @Operation(summary = "更新设备")
    public Result<Device> updateDevice(@PathVariable Long id, @RequestBody Device device) {
        try {
            return Result.success(deviceService.updateDevice(id, device));
        } catch (RuntimeException e) {
            return Result.error("更新设备失败: " + e.getMessage());
        }
    }

    @DeleteMapping("/devices/{id}")
    @org.springframework.security.access.prepost.PreAuthorize("hasRole('SUPERVISOR')")
    @Operation(summary = "删除设备")
    public Result<Boolean> deleteDevice(@PathVariable Long id) {
        try {
            return Result.success(deviceService.deleteDevice(id));
        } catch (RuntimeException e) {
            return Result.error("删除设备失败: " + e.getMessage());
        }
    }

    @GetMapping("/devices/{id}/employee")
    @Operation(summary = "查询设备员工")
    public Result<Employee> getDeviceEmployee(@PathVariable Long id) {
        try {
            Device device = deviceService.getDeviceById(id);
            if (device == null) {
                return Result.error("设备不存在");
            }
            return Result.success(device.getEmployee());
        } catch (Exception e) {
            return Result.error("获取设备使用员工失败: " + e.getMessage());
        }
    }

    @DeleteMapping("/devices/{id}/employee")
    @org.springframework.security.access.prepost.PreAuthorize("hasRole('SUPERVISOR')")
    @Operation(summary = "解除设备员工绑定")
    public Result<Boolean> removeEmployeeFromDevice(@PathVariable Long id) {
        try {
            return Result.success(deviceService.removeEmployeeFromDevice(id));
        } catch (Exception e) {
            return Result.error("解除设备分配失败: " + e.getMessage());
        }
    }

    @GetMapping("/devices/stats")
    @Operation(summary = "查询设备统计")
    public Result<Map<String, Object>> getDeviceStats() {
        try {
            return Result.success(deviceService.getDeviceStats());
        } catch (Exception e) {
            return Result.error("获取设备统计失败: " + e.getMessage());
        }
    }

    @PostMapping("/devices/{deviceCode}/heartbeat")
    @Operation(summary = "设备心跳")
    public Result<Device> heartbeat(@PathVariable String deviceCode, @RequestBody(required = false) DeviceHeartbeatRequest request) {
        try {
            return Result.success(deviceService.heartbeat(deviceCode, request));
        } catch (Exception e) {
            return Result.error("设备心跳失败: " + e.getMessage());
        }
    }

    @GetMapping("/devices/capture-alerts")
    @Operation(summary = "分页查询采集告警")
    public Result<Map<String, Object>> listCaptureAlerts(
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String alertLevel,
            @RequestParam(required = false) String deviceCode,
            @RequestParam(defaultValue = "1") Integer page,
            @RequestParam(defaultValue = "20") Integer size) {
        return Result.success(deviceService.listCaptureAlerts(status, alertLevel, deviceCode, page, size));
    }

    @PostMapping("/devices/capture-alerts/{alertId}/ack")
    @org.springframework.security.access.prepost.PreAuthorize("hasRole('SUPERVISOR')")
    @Operation(summary = "确认采集告警")
    public Result<DeviceCaptureAlert> acknowledgeAlert(
            @PathVariable Long alertId,
            @RequestBody(required = false) DeviceAlertActionRequest request) {
        return Result.success(deviceService.acknowledgeAlert(alertId, request));
    }

    @PostMapping("/devices/capture-alerts/{alertId}/resolve")
    @org.springframework.security.access.prepost.PreAuthorize("hasRole('SUPERVISOR')")
    @Operation(summary = "解决采集告警")
    public Result<DeviceCaptureAlert> resolveAlert(
            @PathVariable Long alertId,
            @RequestBody(required = false) DeviceAlertActionRequest request) {
        return Result.success(deviceService.resolveAlert(alertId, request));
    }
}
