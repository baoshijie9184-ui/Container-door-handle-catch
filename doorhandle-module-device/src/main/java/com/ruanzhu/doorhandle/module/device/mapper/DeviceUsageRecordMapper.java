package com.ruanzhu.doorhandle.module.device.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ruanzhu.doorhandle.module.device.entity.DeviceUsageRecord;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;
import java.util.Map;

/**
 * 设备使用记录Mapper接口
 */
@Mapper
public interface DeviceUsageRecordMapper extends BaseMapper<DeviceUsageRecord> {

    /**
     * 查询指定设备的使用记录
     * @param deviceId 设备ID
     * @return 使用记录列表
     */
    @Select("SELECT * FROM device_usage_record WHERE device_id = #{deviceId} ORDER BY start_time DESC")
    List<DeviceUsageRecord> findByDeviceId(Long deviceId);

    /**
     * 查询指定员工的使用记录
     * @param employeeId 员工ID
     * @return 使用记录列表
     */
    @Select("SELECT * FROM device_usage_record WHERE employee_id = #{employeeId} ORDER BY start_time DESC")
    List<DeviceUsageRecord> findByEmployeeId(Long employeeId);

    /**
     * 查询当前使用中的记录
     * @return 使用中的记录列表
     */
    @Select("SELECT * FROM device_usage_record WHERE status = 'IN_USE' ORDER BY start_time DESC")
    List<DeviceUsageRecord> findActiveRecords();

    /**
     * 查询设备的最新使用记录
     * @param deviceId 设备ID
     * @return 最新使用记录
     */
    @Select("SELECT * FROM device_usage_record WHERE device_id = #{deviceId} ORDER BY start_time DESC LIMIT 1")
    DeviceUsageRecord findLatestByDeviceId(Long deviceId);

    /**
     * 根据条件查询设备使用记录
     * @param params 查询参数
     * @return 查询结果
     */
    List<DeviceUsageRecord> selectRecordsByConditions(Map<String, Object> params);

    /**
     * 根据条件统计设备使用记录数量
     * @param params 查询参数
     * @return 记录数
     */
    int countRecordsByConditions(Map<String, Object> params);
}
