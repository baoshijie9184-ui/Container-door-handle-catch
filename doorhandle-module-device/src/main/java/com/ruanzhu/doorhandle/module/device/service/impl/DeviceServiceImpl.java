package com.ruanzhu.doorhandle.module.device.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.device.dto.device.DeviceAlertActionRequest;
import com.ruanzhu.doorhandle.module.device.dto.device.DeviceHeartbeatRequest;
import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.entity.DeviceCaptureAlert;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceCaptureAlertMapper;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceMapper;
import com.ruanzhu.doorhandle.module.device.service.DeviceService;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.transaction.annotation.Transactional;
import lombok.RequiredArgsConstructor;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 设备管理服务实现类
 */
@Service
@RequiredArgsConstructor
public class DeviceServiceImpl implements DeviceService {
    private final DeviceMapper deviceMapper;
    private final DeviceCaptureAlertMapper deviceCaptureAlertMapper;

    private final ObjectMapper objectMapper = new ObjectMapper();
    
    @Override
    @Cacheable(cacheNames = "device", key = "'all'")
    public List<Device> getAllDevices() {
        return deviceMapper.selectList(null);
    }
    
    @Override
    public List<Device> getAllDevicesWithEmployee() {
        return deviceMapper.findAllWithEmployee();
    }
    
    @Override
    public Map<String, Object> getDevicesByPage(String deviceCode, String deviceType, String modelName, String serialNumber, String status, Integer page, Integer size) {
        // 创建查询条件
        QueryWrapper<Device> queryWrapper = new QueryWrapper<>();
        
        // 添加各个筛选条件
        if (StringUtils.hasText(deviceCode)) {
            queryWrapper.like("device_code", deviceCode);
        }
        if (StringUtils.hasText(deviceType)) {
            queryWrapper.eq("device_type", deviceType);
        }
        if (StringUtils.hasText(modelName)) {
            queryWrapper.like("model_name", modelName);
        }
        if (StringUtils.hasText(serialNumber)) {
            queryWrapper.like("serial_number", serialNumber);
        }
        if (StringUtils.hasText(status)) {
            // 兼容中英文状态值
            Map<String, String[]> statusMapping = Map.of(
                "IN_USE", new String[]{"IN_USE", "使用中"},
                "IDLE", new String[]{"IDLE", "未使用"},
                "MAINTENANCE", new String[]{"MAINTENANCE", "维修中", "维护中"},
                "OFFLINE", new String[]{"OFFLINE", "离线"}
            );
            String[] values = statusMapping.getOrDefault(status.toUpperCase(), new String[]{status});
            queryWrapper.in("status", List.of(values));
        }
        
        // 创建分页对象
        Page<Device> pageParam = new Page<>(page, size);
        
        // 执行分页查询
        Page<Device> pageResult = deviceMapper.selectPage(pageParam, queryWrapper);
        
        // 加载每个设备关联的员工信息
        for (Device device : pageResult.getRecords()) {
            if (device.getEmployeeId() != null) {
                device.setEmployee(deviceMapper.getDeviceWithEmployee(device.getId()).getEmployee());
            }
        }
        
        // 构建返回结果
        Map<String, Object> result = new HashMap<>();
        result.put("records", pageResult.getRecords());
        result.put("total", pageResult.getTotal());
        result.put("page", page);
        result.put("size", size);
        
        return result;
    }
    
    @Override
    @Cacheable(cacheNames = "device", key = "'unassigned'")
    public List<Device> getUnassignedDevices() {
        // 查询employee_id为null的设备，不再限制status
        QueryWrapper<Device> queryWrapper = new QueryWrapper<>();
        queryWrapper.isNull("employee_id");
        
        return deviceMapper.selectList(queryWrapper);
    }
    
    @Override
    @Cacheable(cacheNames = "device", key = "'detail:' + #id", unless = "#result == null")
    public Device getDeviceById(Long id) {
        // 使用关联查询获取设备及其关联的员工信息
        return deviceMapper.getDeviceWithEmployee(id);
    }
    
    @Override
    @Transactional(rollbackFor = Exception.class)
    @CacheEvict(cacheNames = {"device", "dashboard"}, allEntries = true)
    public Device createDevice(Device device) {
        // 检查设备编号是否已存在
        Device existingDevice = deviceMapper.findByDeviceCode(device.getDeviceCode());
        if (existingDevice != null) {
            throw new RuntimeException("设备编号已存在");
        }
        
        deviceMapper.insert(device);
        return device;
    }
    
    @Override
    @Transactional(rollbackFor = Exception.class)
    @CacheEvict(cacheNames = {"device", "dashboard"}, allEntries = true)
    public Device updateDevice(Long id, Device device) {
        // 检查设备是否存在
        Device existingDevice = deviceMapper.selectById(id);
        if (existingDevice == null) {
            throw new RuntimeException("设备不存在");
        }
        if (device.getVersion() == null) {
            throw new com.ruanzhu.doorhandle.common.BusinessException(400, "更新设备必须提供版本号");
        }
        
        // 检查设备编号是否与其他设备冲突
        if (!existingDevice.getDeviceCode().equals(device.getDeviceCode())) {
            Device deviceWithSameCode = deviceMapper.findByDeviceCode(device.getDeviceCode());
            if (deviceWithSameCode != null) {
                throw new RuntimeException("设备编号已被其他设备使用");
            }
        }
        
        // 设置ID确保更新正确的记录
        device.setId(id);
        if (deviceMapper.updateById(device) != 1) {
            throw new com.ruanzhu.doorhandle.common.BusinessException(409, "设备资料已被其他主管更新，请刷新后重试");
        }
        return deviceMapper.selectById(id);
    }
    
    @Override
    @Transactional(rollbackFor = Exception.class)
    @CacheEvict(cacheNames = {"device", "dashboard"}, allEntries = true)
    public boolean deleteDevice(Long id) {
        // 检查设备是否存在
        Device existingDevice = deviceMapper.selectById(id);
        if (existingDevice == null) {
            throw new RuntimeException("设备不存在");
        }
        
        int result = deviceMapper.deleteById(id);
        return result > 0;
    }
    
    @Override
    @Transactional(rollbackFor = Exception.class)
    @CacheEvict(cacheNames = {"device", "dashboard"}, allEntries = true)
    public boolean removeEmployeeFromDevice(Long deviceId) {
        // 检查设备是否存在
        Device existingDevice = deviceMapper.selectById(deviceId);
        if (existingDevice == null) {
            throw new RuntimeException("设备不存在");
        }

        // 如果设备本来就没有关联员工，直接返回成功
        if (existingDevice.getEmployeeId() == null) {
            return true;
        }

        // 更新设备状态为"IDLE"
        existingDevice.setEmployeeId(null);
        existingDevice.setStatus("IDLE");
        existingDevice.setUpdatedTime(LocalDateTime.now());

        // 解除设备与员工的关联并更新状态
        return deviceMapper.updateById(existingDevice) > 0;
    }

    @Override
    @Cacheable(cacheNames = "device", key = "'stats'")
    public Map<String, Object> getDeviceStats() {
        Map<String, Object> stats = new HashMap<>();

        // 总设备数
        long total = deviceMapper.selectCount(null);
        stats.put("total", total);

        // 各状态设备数量
        QueryWrapper<Device> inUseWrapper = new QueryWrapper<>();
        inUseWrapper.in("status", "IN_USE", "使用中");
        long inUse = deviceMapper.selectCount(inUseWrapper);
        stats.put("inUse", inUse);

        QueryWrapper<Device> idleWrapper = new QueryWrapper<>();
        idleWrapper.in("status", "IDLE", "未使用");
        long idle = deviceMapper.selectCount(idleWrapper);
        stats.put("idle", idle);

        QueryWrapper<Device> maintenanceWrapper = new QueryWrapper<>();
        maintenanceWrapper.in("status", "MAINTENANCE", "维修中", "维护中");
        long maintenance = deviceMapper.selectCount(maintenanceWrapper);
        stats.put("maintenance", maintenance);

        QueryWrapper<Device> offlineWrapper = new QueryWrapper<>();
        offlineWrapper.eq("status", "OFFLINE");
        long offline = deviceMapper.selectCount(offlineWrapper);
        stats.put("offline", offline);

        // 已分配设备数
        QueryWrapper<Device> assignedWrapper = new QueryWrapper<>();
        assignedWrapper.isNotNull("employee_id");
        long assigned = deviceMapper.selectCount(assignedWrapper);
        stats.put("assigned", assigned);

        // 未分配设备数
        stats.put("unassigned", total - assigned);

        // 各类型设备数量
        QueryWrapper<Device> captureWrapper = new QueryWrapper<>();
        captureWrapper.eq("device_type", "IMAGE_CAPTURE");
        long imageCapture = deviceMapper.selectCount(captureWrapper);
        stats.put("imageCapture", imageCapture);

        QueryWrapper<Device> detectionWrapper = new QueryWrapper<>();
        detectionWrapper.eq("device_type", "DETECTION");
        long detection = deviceMapper.selectCount(detectionWrapper);
        stats.put("detection", detection);

        // 各类型使用中设备数量
        QueryWrapper<Device> captureInUseWrapper = new QueryWrapper<>();
        captureInUseWrapper.eq("device_type", "IMAGE_CAPTURE").in("status", "IN_USE", "使用中");
        long imageCaptureInUse = deviceMapper.selectCount(captureInUseWrapper);
        stats.put("imageCaptureInUse", imageCaptureInUse);

        QueryWrapper<Device> detectionInUseWrapper = new QueryWrapper<>();
        detectionInUseWrapper.eq("device_type", "DETECTION").in("status", "IN_USE", "使用中");
        long detectionInUse = deviceMapper.selectCount(detectionInUseWrapper);
        stats.put("detectionInUse", detectionInUse);

        return stats;
    }

    @Override
    public boolean existsByDeviceCode(String deviceCode, Long excludeId) {
        LambdaQueryWrapper<Device> wrapper = new LambdaQueryWrapper<Device>()
                .eq(Device::getDeviceCode, deviceCode);
        if (excludeId != null) {
            wrapper.ne(Device::getId, excludeId);
        }
        return deviceMapper.selectCount(wrapper) > 0;
    }

    @Override
    @CacheEvict(cacheNames = {"device", "dashboard"}, allEntries = true)
    public Device heartbeat(String deviceCode) {
        return heartbeat(deviceCode, null);
    }

    @Override
    @CacheEvict(cacheNames = {"device", "dashboard"}, allEntries = true)
    public Device heartbeat(String deviceCode, DeviceHeartbeatRequest request) {
        if (!StringUtils.hasText(deviceCode)) {
            throw new RuntimeException("设备编号不能为空");
        }
        Device device = deviceMapper.findByDeviceCode(deviceCode);
        if (device == null) {
            throw new RuntimeException("设备不存在");
        }

        device.setOnlineStatus("ONLINE");
        device.setLastHeartbeatAt(LocalDateTime.now());
        applyRuntimeSnapshot(device, request);
        if (!"IN_USE".equals(device.getStatus()) && !"MAINTENANCE".equals(device.getStatus())) {
            device.setStatus("IDLE");
        }
        device.setUpdatedTime(LocalDateTime.now());
        deviceMapper.updateById(device);
        createCaptureAlertIfNecessary(device, request);
        return device;
    }

    @Override
    @Cacheable(cacheNames = "device", key = "'capture-alerts:' + T(java.util.Objects).toString(#status, '') + ':' + T(java.util.Objects).toString(#alertLevel, '') + ':' + T(java.util.Objects).toString(#deviceCode, '') + ':' + #page + ':' + #size")
    public Map<String, Object> listCaptureAlerts(String status, String alertLevel, String deviceCode, Integer page, Integer size) {
        Page<DeviceCaptureAlert> pageParam = new Page<>(page == null ? 1 : page, size == null ? 20 : size);
        LambdaQueryWrapper<DeviceCaptureAlert> wrapper = new LambdaQueryWrapper<DeviceCaptureAlert>()
                .orderByDesc(DeviceCaptureAlert::getCreatedAt);
        if (StringUtils.hasText(status)) {
            wrapper.eq(DeviceCaptureAlert::getStatus, status.trim().toUpperCase());
        }
        if (StringUtils.hasText(alertLevel)) {
            wrapper.eq(DeviceCaptureAlert::getAlertLevel, alertLevel.trim().toUpperCase());
        }
        if (StringUtils.hasText(deviceCode)) {
            wrapper.like(DeviceCaptureAlert::getDeviceCode, deviceCode.trim());
        }
        Page<DeviceCaptureAlert> pageResult = deviceCaptureAlertMapper.selectPage(pageParam, wrapper);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("records", pageResult.getRecords());
        result.put("total", pageResult.getTotal());
        result.put("page", pageParam.getCurrent());
        result.put("size", pageParam.getSize());
        result.put("status", status);
        result.put("alertLevel", alertLevel);
        result.put("deviceCode", deviceCode);
        return result;
    }

    @Override
    @CacheEvict(cacheNames = {"device", "dashboard"}, allEntries = true)
    public DeviceCaptureAlert acknowledgeAlert(Long alertId, DeviceAlertActionRequest request) {
        DeviceCaptureAlert alert = getAlert(alertId);
        alert.setStatus("ACKNOWLEDGED");
        alert.setAckOperator(resolveOperator(request));
        alert.setAckRemark(request == null ? null : request.getRemark());
        alert.setAcknowledgedAt(LocalDateTime.now());
        alert.setUpdatedAt(LocalDateTime.now());
        deviceCaptureAlertMapper.updateById(alert);
        return alert;
    }

    @Override
    @CacheEvict(cacheNames = {"device", "dashboard"}, allEntries = true)
    public DeviceCaptureAlert resolveAlert(Long alertId, DeviceAlertActionRequest request) {
        DeviceCaptureAlert alert = getAlert(alertId);
        alert.setStatus("RESOLVED");
        alert.setResolvedOperator(resolveOperator(request));
        alert.setResolvedRemark(request == null ? null : request.getRemark());
        alert.setResolvedAt(LocalDateTime.now());
        alert.setUpdatedAt(LocalDateTime.now());
        deviceCaptureAlertMapper.updateById(alert);
        return alert;
    }

    private DeviceCaptureAlert getAlert(Long alertId) {
        DeviceCaptureAlert alert = deviceCaptureAlertMapper.selectById(alertId);
        if (alert == null) {
            throw new RuntimeException("采集异常告警不存在");
        }
        return alert;
    }

    private void applyRuntimeSnapshot(Device device, DeviceHeartbeatRequest request) {
        if (request == null) {
            return;
        }
        device.setStationCode(request.getStationCode());
        device.setEdgeNodeId(request.getEdgeNodeId());
        device.setPlcStatus(request.getPlcStatus());
        device.setCameraStatus(request.getCameraStatus());
        device.setCaptureStatus(request.getCaptureStatus());
        device.setLastImageKey(request.getLastImageKey());
        device.setLastCaptureAt(parseDateTime(request.getLastCaptureAt()));
        device.setRuntimeMetadataJson(writeJson(request.getRuntimeMetadata()));
    }

    private void createCaptureAlertIfNecessary(Device device, DeviceHeartbeatRequest request) {
        if (request == null || !isCaptureException(request)) {
            return;
        }
        LocalDateTime now = LocalDateTime.now();
        DeviceCaptureAlert alert = new DeviceCaptureAlert();
        alert.setAlertId("ALERT-" + now.toString().replaceAll("[^0-9]", "") + "-" + UUID.randomUUID().toString().replace("-", "").substring(0, 6));
        alert.setDeviceId(device.getId());
        alert.setDeviceCode(device.getDeviceCode());
        alert.setDeviceType(device.getDeviceType());
        alert.setStationCode(device.getStationCode());
        alert.setEdgeNodeId(device.getEdgeNodeId());
        alert.setAlertType("CAPTURE_EXCEPTION");
        alert.setAlertLevel(StringUtils.hasText(request.getAlertLevel()) ? request.getAlertLevel().trim().toUpperCase() : "MAJOR");
        alert.setAlertMessage(StringUtils.hasText(request.getAlertMessage()) ? request.getAlertMessage() : "采集端状态异常: " + request.getCaptureStatus());
        alert.setRuntimeSnapshotJson(buildRuntimeSnapshotJson(device, request));
        alert.setStatus("OPEN");
        alert.setCreatedAt(now);
        alert.setUpdatedAt(now);
        deviceCaptureAlertMapper.insert(alert);
    }

    private boolean isCaptureException(DeviceHeartbeatRequest request) {
        return isRuntimeError(request.getCaptureStatus())
                || isRuntimeError(request.getCameraStatus())
                || isRuntimeError(request.getPlcStatus())
                || StringUtils.hasText(request.getAlertMessage());
    }

    private boolean isRuntimeError(String status) {
        if (!StringUtils.hasText(status)) {
            return false;
        }
        String normalized = status.trim().toUpperCase();
        return normalized.contains("ERROR")
                || normalized.contains("FAIL")
                || normalized.contains("TIMEOUT")
                || normalized.contains("EXCEPTION")
                || normalized.contains("ALARM");
    }

    private String buildRuntimeSnapshotJson(Device device, DeviceHeartbeatRequest request) {
        Map<String, Object> snapshot = new LinkedHashMap<>();
        snapshot.put("deviceCode", device.getDeviceCode());
        snapshot.put("stationCode", request.getStationCode());
        snapshot.put("edgeNodeId", request.getEdgeNodeId());
        snapshot.put("plcStatus", request.getPlcStatus());
        snapshot.put("cameraStatus", request.getCameraStatus());
        snapshot.put("captureStatus", request.getCaptureStatus());
        snapshot.put("lastImageKey", request.getLastImageKey());
        snapshot.put("lastCaptureAt", request.getLastCaptureAt());
        snapshot.put("runtimeMetadata", request.getRuntimeMetadata());
        return writeJson(snapshot);
    }

    private String writeJson(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException ex) {
            throw new RuntimeException("序列化设备运行状态失败: " + ex.getMessage(), ex);
        }
    }

    private LocalDateTime parseDateTime(String value) {
        if (!StringUtils.hasText(value)) {
            return null;
        }
        try {
            return OffsetDateTime.parse(value).toLocalDateTime();
        } catch (Exception ignored) {
            return LocalDateTime.parse(value);
        }
    }

    private String resolveOperator(DeviceAlertActionRequest request) {
        return request != null && StringUtils.hasText(request.getOperator()) ? request.getOperator() : "system";
    }
}
