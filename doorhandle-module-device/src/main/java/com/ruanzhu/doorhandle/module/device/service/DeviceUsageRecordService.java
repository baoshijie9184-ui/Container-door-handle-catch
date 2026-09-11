package com.ruanzhu.doorhandle.module.device.service;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.IService;
import com.ruanzhu.doorhandle.module.device.entity.DeviceUsageRecord;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * 设备使用记录服务接口
 */
public interface DeviceUsageRecordService extends IService<DeviceUsageRecord> {
    
    /**
     * 分页查询设备使用记录
     * @param page 页码
     * @param size 每页大小
     * @param deviceId 设备ID
     * @param deviceCode 设备编号
     * @param employeeName 员工姓名
     * @param employeeNumber 员工编号
     * @param status 状态
     * @param startTimeBegin 开始时间范围起点
     * @param startTimeEnd 开始时间范围终点
     * @return 分页结果
     */
    Map<String, Object> getDeviceUsageRecords(Integer page, Integer size, Long deviceId, String deviceCode,
            String employeeName, String employeeNumber, String status,
            String startTimeBegin, String startTimeEnd);
    
    /**
     * 根据ID获取使用记录详情
     * @param id 记录ID
     * @return 使用记录信息
     */
    DeviceUsageRecord getById(Long id);
    
    /**
     * 创建设备使用记录
     * @param record 设备使用记录
     * @return 是否成功
     */
    boolean createRecord(DeviceUsageRecord record);
    
    /**
     * 更新设备使用记录
     * @param record 设备使用记录
     * @return 是否成功
     */
    boolean updateRecord(DeviceUsageRecord record);
    
    /**
     * 归还设备
     * @param recordId 记录ID
     * @param remarks 备注信息
     * @return 是否成功
     */
    boolean returnDevice(Long recordId, String remarks);
    
    /**
     * 删除使用记录
     * @param id 记录ID
     * @return 是否成功
     */
    boolean deleteRecord(Long id);
    
    /**
     * 获取设备的使用记录
     * @param deviceId 设备ID
     * @return 使用记录列表
     */
    List<DeviceUsageRecord> getRecordsByDeviceId(Long deviceId);
    
    /**
     * 获取员工的使用记录
     * @param employeeId 员工ID
     * @return 使用记录列表
     */
    List<DeviceUsageRecord> getRecordsByEmployeeId(Long employeeId);
    
    /**
     * 获取当前使用中的记录
     * @return 使用中的记录列表
     */
    List<DeviceUsageRecord> getActiveRecords();
    
    /**
     * 设备分配时自动创建使用记录
     * @param deviceId 设备ID
     * @param employeeId 员工ID
     * @param remarks 备注信息
     * @return 是否成功
     */
    boolean createRecordOnAssign(Long deviceId, Long employeeId, String remarks);
    
    /**
     * 设备解除分配时自动更新使用记录
     * @param deviceId 设备ID
     * @param remarks 备注信息
     * @return 是否成功
     */
    boolean updateRecordOnUnassign(Long deviceId, String remarks);

    /**
     * 根据设备ID查询使用记录
     *
     * @param deviceId 设备ID
     * @return 使用记录列表
     */
    List<DeviceUsageRecord> getDeviceUsageRecordsByDeviceId(Long deviceId);

    /**
     * 创建设备使用记录
     *
     * @param deviceUsageRecord 设备使用记录
     */
    void createDeviceUsageRecord(DeviceUsageRecord deviceUsageRecord);

    /**
     * 更新设备使用记录
     *
     * @param deviceUsageRecord 设备使用记录
     */
    void updateDeviceUsageRecord(DeviceUsageRecord deviceUsageRecord);

    /**
     * 删除设备使用记录
     *
     * @param id 记录ID
     */
    void deleteDeviceUsageRecord(Long id);
} 