package com.ruanzhu.doorhandle.module.device.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.entity.DeviceUsageRecord;
import com.ruanzhu.doorhandle.module.device.entity.Employee;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceMapper;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceUsageRecordMapper;
import com.ruanzhu.doorhandle.module.device.mapper.EmployeeMapper;
import com.ruanzhu.doorhandle.module.device.service.DeviceUsageRecordService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 设备使用记录服务实现类
 */
@Slf4j
@Service
public class DeviceUsageRecordServiceImpl extends ServiceImpl<DeviceUsageRecordMapper, DeviceUsageRecord> implements DeviceUsageRecordService {
    
    @Autowired
    private DeviceUsageRecordMapper deviceUsageRecordMapper;
    
    @Autowired
    private DeviceMapper deviceMapper;
    
    @Autowired
    private EmployeeMapper employeeMapper;
    
    private static final DateTimeFormatter DATE_TIME_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    /**
     * 状态值映射: 英文 -> 中英文兼容列表
     * 数据库可能存在中文或英文状态值，查询时需要同时匹配
     */
    private static final Map<String, List<String>> STATUS_MAPPING = Map.of(
            "IN_USE", List.of("IN_USE", "使用中"),
            "RETURNED", List.of("RETURNED", "已归还")
    );

    @Override
    public Map<String, Object> getDeviceUsageRecords(Integer page, Integer size, Long deviceId, String deviceCode,
                                               String employeeName, String employeeNumber, String status,
                                               String startTimeBegin, String startTimeEnd) {
        log.info("分页查询设备使用记录: page={}, size={}, deviceId={}, deviceCode={}, employeeName={}, employeeNumber={}, status={}, startTimeBegin={}, startTimeEnd={}",
                page, size, deviceId, deviceCode, employeeName, employeeNumber, status, startTimeBegin, startTimeEnd);

        // 构建查询参数
        Map<String, Object> params = new HashMap<>();
        if (deviceId != null) {
            params.put("deviceId", deviceId);
        }
        if (StringUtils.hasText(deviceCode)) {
            params.put("deviceCode", deviceCode);
        }
        if (StringUtils.hasText(employeeName)) {
            params.put("employeeName", employeeName);
        }
        if (StringUtils.hasText(employeeNumber)) {
            params.put("employeeNumber", employeeNumber);
        }
        if (StringUtils.hasText(status)) {
            // 兼容中英文状态值
            List<String> statusList = STATUS_MAPPING.getOrDefault(status, List.of(status));
            params.put("statusList", statusList);
        }
        
        // 处理时间范围
        LocalDateTime startTimeBeginDate = null;
        LocalDateTime startTimeEndDate = null;
        if (StringUtils.hasText(startTimeBegin)) {
            startTimeBeginDate = LocalDateTime.parse(startTimeBegin, DATE_TIME_FORMATTER);
            params.put("startTimeBegin", startTimeBeginDate);
        }
        if (StringUtils.hasText(startTimeEnd)) {
            startTimeEndDate = LocalDateTime.parse(startTimeEnd, DATE_TIME_FORMATTER);
            params.put("startTimeEnd", startTimeEndDate);
        }

        // 执行查询
        int offset = (page - 1) * size;
        params.put("offset", offset);
        params.put("limit", size);
        
        // 使用手动SQL查询替代MybatisPlus的Page查询
        List<DeviceUsageRecord> records = deviceUsageRecordMapper.selectRecordsByConditions(params);
        int total = deviceUsageRecordMapper.countRecordsByConditions(params);
        
        log.info("查询到{}条设备使用记录", records.size());
        
        // 构建返回结果
        Map<String, Object> result = new HashMap<>();
        result.put("records", records);
        result.put("total", total);
        result.put("size", size);
        result.put("current", page);
        result.put("pages", (total + size - 1) / size);
        
        return result;
    }

    @Override
    public List<DeviceUsageRecord> getDeviceUsageRecordsByDeviceId(Long deviceId) {
        log.info("查询设备ID={}的使用记录", deviceId);
        return deviceUsageRecordMapper.findByDeviceId(deviceId);
    }

    @Override
    @Transactional
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DEVICE_USAGE",action="createDeviceUsageRecord",resource="arg0.id",supervisorOnly=true)
    public void createDeviceUsageRecord(DeviceUsageRecord deviceUsageRecord) {
        log.info("创建设备使用记录: {}", deviceUsageRecord);
        
        // 设置默认值
        if (deviceUsageRecord.getStartTime() == null) {
            deviceUsageRecord.setStartTime(LocalDateTime.now());
        }
        if (!StringUtils.hasText(deviceUsageRecord.getStatus())) {
            deviceUsageRecord.setStatus("IN_USE");
        }
        
        // 保存记录
        deviceUsageRecordMapper.insert(deviceUsageRecord);
        
        // 如果指定了设备ID，更新设备状态
        if (deviceUsageRecord.getDeviceId() != null) {
            Device device = deviceMapper.selectById(deviceUsageRecord.getDeviceId());
            if (device != null) {
                device.setStatus("IN_USE");
                device.setEmployeeId(deviceUsageRecord.getEmployeeId());
                deviceMapper.updateById(device);
            }
        }
    }

    @Override
    @Transactional
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DEVICE_USAGE",action="updateDeviceUsageRecord",resource="arg0.id",supervisorOnly=true)
    public void updateDeviceUsageRecord(DeviceUsageRecord deviceUsageRecord) {
        log.info("更新设备使用记录: {}", deviceUsageRecord);
        
        DeviceUsageRecord existingRecord = deviceUsageRecordMapper.selectById(deviceUsageRecord.getId());
        if (existingRecord == null) {
            log.warn("要更新的设备使用记录不存在: {}", deviceUsageRecord.getId());
            return;
        }
        
        // 如果状态从"IN_USE"变为"RETURNED"，则设置归还时间
        if ("IN_USE".equals(existingRecord.getStatus()) && "RETURNED".equals(deviceUsageRecord.getStatus())) {
            if (deviceUsageRecord.getEndTime() == null) {
                deviceUsageRecord.setEndTime(LocalDateTime.now());
            }
            
            // 更新设备状态
            if (existingRecord.getDeviceId() != null) {
                Device device = deviceMapper.selectById(existingRecord.getDeviceId());
                if (device != null) {
                    device.setStatus("IDLE");
                    device.setEmployeeId(null);
                    deviceMapper.updateById(device);
                }
            }
        }
        
        // 更新记录
        deviceUsageRecordMapper.updateById(deviceUsageRecord);
    }

    @Override
    @Transactional
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DEVICE_USAGE",action="deleteDeviceUsageRecord",supervisorOnly=true)
    public void deleteDeviceUsageRecord(Long id) {
        log.info("删除设备使用记录ID={}", id);
        
        DeviceUsageRecord record = deviceUsageRecordMapper.selectById(id);
        if (record == null) {
            log.warn("要删除的设备使用记录不存在: {}", id);
            return;
        }
        
        // 如果记录状态为"IN_USE"，需要更新设备状态
        if ("IN_USE".equals(record.getStatus()) && record.getDeviceId() != null) {
            Device device = deviceMapper.selectById(record.getDeviceId());
            if (device != null && device.getEmployeeId() != null && 
                device.getEmployeeId().equals(record.getEmployeeId())) {
                device.setStatus("IDLE");
                device.setEmployeeId(null);
                deviceMapper.updateById(device);
            }
        }
        
        // 删除记录
        deviceUsageRecordMapper.deleteById(id);
    }

    @Override
    public DeviceUsageRecord getById(Long id) {
        return deviceUsageRecordMapper.selectById(id);
    }

    @Override
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="RESOURCE",action="createRecord",supervisorOnly=true)
    public boolean createRecord(DeviceUsageRecord record) {
        if (record.getStartTime() == null) {
            record.setStartTime(LocalDateTime.now());
        }
        
        if (!StringUtils.hasText(record.getStatus())) {
            record.setStatus("IN_USE");
        }

        return save(record);
    }

    @Override
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="RESOURCE",action="updateRecord",supervisorOnly=true)
    public boolean updateRecord(DeviceUsageRecord record) {
        return updateById(record);
    }

    @Override
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="RESOURCE",action="deleteRecord",supervisorOnly=true)
    public boolean deleteRecord(Long id) {
        return removeById(id);
    }

    @Override
    public List<DeviceUsageRecord> getRecordsByDeviceId(Long deviceId) {
        return deviceUsageRecordMapper.findByDeviceId(deviceId);
    }

    @Override
    public List<DeviceUsageRecord> getRecordsByEmployeeId(Long employeeId) {
        QueryWrapper<DeviceUsageRecord> queryWrapper = new QueryWrapper<>();
        queryWrapper.eq("employee_id", employeeId);
        queryWrapper.orderByDesc("start_time");
        return list(queryWrapper);
    }

    @Override
    public List<DeviceUsageRecord> getActiveRecords() {
        QueryWrapper<DeviceUsageRecord> queryWrapper = new QueryWrapper<>();
        queryWrapper.eq("status", "IN_USE");
        queryWrapper.isNull("end_time");
        queryWrapper.orderByDesc("start_time");
        return list(queryWrapper);
    }

    @Override
    @Transactional
    public boolean returnDevice(Long id, String remarks) {
        DeviceUsageRecord record = getById(id);
        if (record == null) {
            return false;
        }

        // 更新记录状态
        record.setStatus("RETURNED");
        record.setEndTime(LocalDateTime.now());
        
        if (StringUtils.hasText(remarks)) {
            record.setRemarks(remarks);
        }
        
        boolean updated = updateById(record);
        
        // 更新设备状态
        if (updated && record.getDeviceId() != null) {
            Device device = deviceMapper.selectById(record.getDeviceId());
            if (device != null) {
                device.setStatus("IDLE");
                device.setEmployeeId(null);
                deviceMapper.updateById(device);
            }
        }
        
        return updated;
    }

    @Override
    @Transactional
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="RESOURCE",action="createRecordOnAssign",supervisorOnly=true)
    public boolean createRecordOnAssign(Long deviceId, Long employeeId, String remarks) {
        if (deviceId == null || employeeId == null) {
            return false;
        }
        
        // 获取设备和员工信息
        Device device = deviceMapper.selectById(deviceId);
        Employee employee = employeeMapper.selectById(employeeId);
        
        if (device == null || employee == null) {
            return false;
        }
        
        // 创建新的使用记录
        DeviceUsageRecord record = new DeviceUsageRecord();
        record.setDeviceId(deviceId);
        record.setDeviceCode(device.getDeviceCode());
        record.setDeviceType(device.getDeviceType());
        record.setModelName(device.getModelName());
        record.setSerialNumber(device.getSerialNumber());
        
        record.setEmployeeId(employeeId);
        record.setEmployeeName(employee.getName());
        record.setEmployeeNumber(employee.getEmployeeNumber());
        record.setContact(employee.getContact());
        
        record.setStartTime(LocalDateTime.now());
        record.setStatus("IN_USE");
        record.setRemarks(remarks);
        
        boolean saved = save(record);
        
        // 更新设备状态
        if (saved) {
            device.setStatus("IN_USE");
            device.setEmployeeId(employeeId);
            deviceMapper.updateById(device);
        }
        
        return saved;
    }

    @Override
    @Transactional
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="RESOURCE",action="updateRecordOnUnassign",supervisorOnly=true)
    public boolean updateRecordOnUnassign(Long deviceId, String remarks) {
        if (deviceId == null) {
            return false;
        }
        
        Device device = deviceMapper.selectById(deviceId);
        if (device == null || device.getEmployeeId() == null) {
            return false;
        }
        
        // 查找该设备的最新使用中记录
        QueryWrapper<DeviceUsageRecord> queryWrapper = new QueryWrapper<>();
        queryWrapper.eq("device_id", deviceId);
        queryWrapper.eq("status", "IN_USE");
        queryWrapper.isNull("end_time");
        queryWrapper.orderByDesc("start_time");
        queryWrapper.last("LIMIT 1");
        
        DeviceUsageRecord record = getOne(queryWrapper);
        if (record == null) {
            return false;
        }
        
        // 更新记录
        record.setStatus("RETURNED");
        record.setEndTime(LocalDateTime.now());
        
        if (StringUtils.hasText(remarks)) {
            record.setRemarks(remarks);
        }
        
        boolean updated = updateById(record);
        
        // 更新设备状态
        if (updated) {
            device.setStatus("IDLE");
            device.setEmployeeId(null);
            deviceMapper.updateById(device);
        }
        
        return updated;
    }
} 
