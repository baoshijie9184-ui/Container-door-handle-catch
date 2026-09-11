package com.ruanzhu.doorhandle.module.device.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.device.entity.DeviceUsageRecord;
import com.ruanzhu.doorhandle.module.device.service.DeviceUsageRecordService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 设备使用记录控制器
 */
@RestController
@RequestMapping("/api/device-usage-records")
@Slf4j
public class DeviceUsageRecordController {
    
    @Autowired
    private DeviceUsageRecordService deviceUsageRecordService;
    
    /**
     * 分页查询设备使用记录
     */
    @GetMapping
    public Result getDeviceUsageRecords(
            @RequestParam(defaultValue = "1") Integer page,
            @RequestParam(defaultValue = "10") Integer size,
            @RequestParam(required = false) Long deviceId,
            @RequestParam(required = false) String deviceCode,
            @RequestParam(required = false) String employeeName,
            @RequestParam(required = false) String employeeNumber,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String startTimeBegin,
            @RequestParam(required = false) String startTimeEnd) {

        log.info("查询设备使用记录，参数: page={}, size={}, deviceId={}, deviceCode={}, employeeName={}, employeeNumber={}, status={}, startTimeBegin={}, startTimeEnd={}",
                page, size, deviceId, deviceCode, employeeName, employeeNumber, status, startTimeBegin, startTimeEnd);

        Map<String, Object> result = deviceUsageRecordService.getDeviceUsageRecords(page, size, deviceId, deviceCode, employeeName, employeeNumber, status, startTimeBegin, startTimeEnd);
        
        log.info("查询到设备使用记录: {}", result);
        return Result.success(result);
    }
    
    /**
     * 查询指定设备的使用记录
     */
    @GetMapping("/device/{deviceId}")
    public Result getDeviceUsageRecordsByDeviceId(@PathVariable Long deviceId) {
        log.info("查询设备ID={}的使用记录", deviceId);
        List<DeviceUsageRecord> records = deviceUsageRecordService.getDeviceUsageRecordsByDeviceId(deviceId);
        log.info("查询到设备ID={}的使用记录数量: {}", deviceId, records.size());
        return Result.success(records);
    }
    
    /**
     * 创建设备使用记录
     */
    @PostMapping
    @org.springframework.security.access.prepost.PreAuthorize("hasRole('SUPERVISOR')")
    public Result createDeviceUsageRecord(@RequestBody DeviceUsageRecord deviceUsageRecord) {
        log.info("创建设备使用记录: {}", deviceUsageRecord);
        deviceUsageRecordService.createDeviceUsageRecord(deviceUsageRecord);
        return Result.success();
    }
    
    /**
     * 更新设备使用记录
     */
    @PutMapping("/{id}")
    @org.springframework.security.access.prepost.PreAuthorize("hasRole('SUPERVISOR')")
    public Result updateDeviceUsageRecord(@PathVariable Long id, @RequestBody DeviceUsageRecord deviceUsageRecord) {
        log.info("更新设备使用记录ID={}: {}", id, deviceUsageRecord);
        deviceUsageRecord.setId(id);
        deviceUsageRecordService.updateDeviceUsageRecord(deviceUsageRecord);
        return Result.success();
    }
    
    /**
     * 删除设备使用记录
     */
    @DeleteMapping("/{id}")
    @org.springframework.security.access.prepost.PreAuthorize("hasRole('SUPERVISOR')")
    public Result deleteDeviceUsageRecord(@PathVariable Long id) {
        log.info("删除设备使用记录ID={}", id);
        deviceUsageRecordService.deleteDeviceUsageRecord(id);
        return Result.success();
    }
}
