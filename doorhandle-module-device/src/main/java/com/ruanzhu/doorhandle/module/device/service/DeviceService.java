package com.ruanzhu.doorhandle.module.device.service;

import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.entity.DeviceCaptureAlert;
import com.ruanzhu.doorhandle.module.device.dto.device.DeviceAlertActionRequest;
import com.ruanzhu.doorhandle.module.device.dto.device.DeviceHeartbeatRequest;

import java.util.List;
import java.util.Map;

/**
 * 设备管理服务接口
 */
public interface DeviceService {
    
    /**
     * 获取所有设备列表
     */
    List<Device> getAllDevices();
    
    /**
     * 获取所有设备列表，包含员工信息
     */
    List<Device> getAllDevicesWithEmployee();
    
    /**
     * 分页查询设备列表
     * @param deviceCode 设备编号
     * @param deviceType 设备类型
     * @param modelName 设备型号
     * @param serialNumber 序列号
     * @param status 设备状态
     * @param page 页码
     * @param size 每页大小
     * @return 包含设备列表和总数的Map
     */
    Map<String, Object> getDevicesByPage(String deviceCode, String deviceType, String modelName, String serialNumber, String status, Integer page, Integer size);
    
    /**
     * 获取所有未分配给员工的设备
     * @return 未分配的设备列表
     */
    List<Device> getUnassignedDevices();
    
    /**
     * 根据ID获取设备详情
     */
    Device getDeviceById(Long id);
    
    /**
     * 创建设备
     */
    Device createDevice(Device device);
    
    /**
     * 更新设备信息
     */
    Device updateDevice(Long id, Device device);
    
    /**
     * 删除设备
     */
    boolean deleteDevice(Long id);
    
    /**
     * 解除设备与员工的关联
     */
    boolean removeEmployeeFromDevice(Long deviceId);

    /**
     * 获取设备统计信息
     * @return 包含各状态设备数量的统计Map
     */
    Map<String, Object> getDeviceStats();

    /**
     * 检查设备编号是否已存在
     */
    boolean existsByDeviceCode(String deviceCode, Long excludeId);

    /**
     * 采集端设备心跳
     */
    Device heartbeat(String deviceCode);

    /**
     * 采集端设备心跳，携带工位/PLC/相机/边缘节点运行态
     */
    Device heartbeat(String deviceCode, DeviceHeartbeatRequest request);

    /**
     * 查询采集异常告警
     */
    Map<String, Object> listCaptureAlerts(String status, String alertLevel, String deviceCode, Integer page, Integer size);

    /**
     * 确认采集异常告警
     */
    DeviceCaptureAlert acknowledgeAlert(Long alertId, DeviceAlertActionRequest request);

    /**
     * 关闭采集异常告警
     */
    DeviceCaptureAlert resolveAlert(Long alertId, DeviceAlertActionRequest request);
} 
