package com.ruanzhu.doorhandle.module.device.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.ruanzhu.doorhandle.common.BusinessException;
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
        validateChangedReferences(deviceUsageRecord, null);
        deviceUsageRecord.setVersion(0L);
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
        
        DeviceUsageRecord existingRecord = deviceUsageRecordMapper.selectForReferenceUpdate(deviceUsageRecord.getId());
        if (existingRecord == null) {
            log.warn("要更新的设备使用记录不存在: {}", deviceUsageRecord.getId());
            return;
        }
        validateChangedReferences(deviceUsageRecord, existingRecord);
        
        // 如果状态从"IN_USE"变为"RETURNED"，则设置归还时间
        if ("IN_USE".equals(existingRecord.getStatus()) && "RETURNED".equals(deviceUsageRecord.getStatus())) {
            if (deviceUsageRecord.getEndTime() == null) {
                deviceUsageRecord.setEndTime(LocalDateTime.now());
            }
            
            // 更新设备状态
            releaseCurrentAssignment(lockCurrentAssignment(existingRecord));
        }
        
        // 更新记录
        deviceUsageRecordMapper.updateById(deviceUsageRecord);
    }

    @Override
    @Transactional
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DEVICE_USAGE",action="deleteDeviceUsageRecord",supervisorOnly=true)
    public void deleteDeviceUsageRecord(Long id) {
        log.info("删除设备使用记录ID={}", id);
        
        DeviceUsageRecord record = deviceUsageRecordMapper.selectForReferenceUpdate(id);
        if (record == null) {
            log.warn("要删除的设备使用记录不存在: {}", id);
            return;
        }
        
        // 如果记录状态为"IN_USE"，需要更新设备状态
        releaseCurrentAssignment(lockCurrentAssignment(record));
        
        // 删除记录
        deviceUsageRecordMapper.deleteById(id);
    }

    @Override
    public DeviceUsageRecord getById(Long id) {
        return deviceUsageRecordMapper.selectById(id);
    }

    @Override
    @Transactional
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DEVICE_USAGE",action="createRecord",supervisorOnly=true)
    public boolean createRecord(DeviceUsageRecord record) {
        validateChangedReferences(record, null);
        record.setVersion(0L);
        if (record.getStartTime() == null) {
            record.setStartTime(LocalDateTime.now());
        }
        
        if (!StringUtils.hasText(record.getStatus())) {
            record.setStatus("IN_USE");
        }

        return save(record);
    }

    @Override
    @Transactional
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DEVICE_USAGE",action="updateRecord",supervisorOnly=true)
    public boolean updateRecord(DeviceUsageRecord record) {
        DeviceUsageRecord existing = deviceUsageRecordMapper.selectForReferenceUpdate(record.getId());
        if (existing == null) return false;
        validateChangedReferences(record, existing);
        return updateById(record);
    }

    @Override
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DEVICE_USAGE",action="deleteRecord",supervisorOnly=true)
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
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DEVICE_USAGE",action="returnDevice",supervisorOnly=true)
    public boolean returnDevice(Long id, String remarks) {
        DeviceUsageRecord record = deviceUsageRecordMapper.selectForReferenceUpdate(id);
        if (record == null) {
            return false;
        }
        if (record.getEndTime() != null || "RETURNED".equals(record.getStatus()) || "已归还".equals(record.getStatus())) return true;
        Device assigned = lockCurrentAssignment(record);

        // 更新记录状态
        record.setStatus("RETURNED");
        record.setEndTime(LocalDateTime.now());
        
        if (StringUtils.hasText(remarks)) {
            record.setRemarks(remarks);
        }
        
        boolean updated = updateById(record);
        
        // 更新设备状态
        if (updated) releaseCurrentAssignment(assigned);
        
        return updated;
    }

    @Override
    @Transactional
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DEVICE",action="USAGE_ASSIGN",supervisorOnly=true)
    public boolean createRecordOnAssign(Long deviceId, Long employeeId, String remarks) {
        if (deviceId == null || employeeId == null) {
            return false;
        }
        
        // 获取设备和员工信息
        Employee employee = employeeMapper.selectForUsageReference(employeeId);
        Device device = deviceMapper.selectForUsageReference(deviceId);
        
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

    private void validateChangedReferences(DeviceUsageRecord record, DeviceUsageRecord existing) {
        // Old references survive parent deletion. Only introducing a different non-null ID
        // needs a live parent; omitted IDs retain MyBatis' existing partial-update contract.
        Long employeeId = record.getEmployeeId();
        if (employeeId != null && (existing == null || !employeeId.equals(existing.getEmployeeId()))) {
            if (employeeId < 1 || employeeMapper.selectForUsageReference(employeeId) == null)
                throw new BusinessException(400, "关联员工不存在，请重新选择");
        }
        Long deviceId = record.getDeviceId();
        if (deviceId != null && (existing == null || !deviceId.equals(existing.getDeviceId()))) {
            if (deviceId < 1 || deviceMapper.selectForUsageReference(deviceId) == null)
                throw new BusinessException(400, "关联设备不存在，请重新选择");
        }
    }

    private Device lockCurrentAssignment(DeviceUsageRecord record) {
        if (record.getDeviceId() == null || record.getEmployeeId() == null || !openUsage(record)) return null;
        Device device = deviceMapper.selectForUsageUpdate(record.getDeviceId());
        if (device == null || !record.getEmployeeId().equals(device.getEmployeeId())) return null;
        DeviceUsageRecord newest = deviceUsageRecordMapper.selectNewestForDeviceUpdate(record.getDeviceId());
        return newest != null && java.util.Objects.equals(record.getId(), newest.getId())
                && record.getEmployeeId().equals(newest.getEmployeeId()) && openUsage(newest) ? device : null;
    }

    private static boolean openUsage(DeviceUsageRecord record) {
        return record.getEndTime() == null && ("IN_USE".equals(record.getStatus()) || "使用中".equals(record.getStatus()));
    }

    private void releaseCurrentAssignment(Device device) {
        if (device == null) return;
        // Use the explicit nullable update, not MyBatis' NOT_NULL entity update strategy.
        if (deviceMapper.updateEmployeeId(device.getId(), null) != 1)
            throw new BusinessException(409, "设备状态已变化，请刷新后重试");
    }

    @Override
    @Transactional
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DEVICE",action="USAGE_RETURN",supervisorOnly=true)
    public boolean updateRecordOnUnassign(Long deviceId, String remarks) {
        if (deviceId == null) {
            return false;
        }
        
        Device device = deviceMapper.selectForUsageUpdate(deviceId);
        if (device == null || device.getEmployeeId() == null) {
            return false;
        }
        
        // The compound audit captures this same latest allocation ID. Never fall
        // back to an older open row when the latest receipt is already closed.
        DeviceUsageRecord record = deviceUsageRecordMapper.selectNewestForDeviceUpdate(deviceId);
        if (record == null || !openUsage(record) || !device.getEmployeeId().equals(record.getEmployeeId())) {
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
        if (updated) releaseCurrentAssignment(device);
        
        return updated;
    }
} 
