package com.ruanzhu.doorhandle.module.device.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ruanzhu.doorhandle.module.device.entity.Device;
import org.apache.ibatis.annotations.*;

import java.util.List;

/**
 * 设备Mapper接口
 */
@Mapper
public interface DeviceMapper extends BaseMapper<Device> {
    
    /**
     * 根据员工ID查询分配给该员工的设备列表
     * @param employeeId 员工ID
     * @return 设备列表
     */
    @Select("SELECT d.* FROM device_management d WHERE d.employee_id = #{employeeId}")
    List<Device> findByEmployeeId(Long employeeId);
    
    /**
     * 根据设备编号查询设备
     */
    @Select("SELECT * FROM device_management WHERE device_code = #{deviceCode}")
    Device findByDeviceCode(String deviceCode);
    
    /**
     * 更新设备的员工ID
     * @param deviceId 设备ID
     * @param employeeId 员工ID（可为null，表示解除分配）
     * @return 受影响的行数
     */
    @Update("UPDATE device_management SET employee_id = #{employeeId}, status = CASE WHEN #{employeeId} IS NULL THEN 'IDLE' ELSE 'IN_USE' END WHERE id = #{deviceId}")
    int updateEmployeeId(@Param("deviceId") Long deviceId, @Param("employeeId") Long employeeId);
    
    /**
     * 解除员工关联的所有设备
     * @param employeeId 员工ID
     * @return 受影响的行数
     */
    @Update("UPDATE device_management SET employee_id = NULL, status = 'IDLE' WHERE employee_id = #{employeeId}")
    int removeEmployeeFromDevices(Long employeeId);
    
    /**
     * 查询设备详情，包括关联的员工信息
     * @param id 设备ID
     * @return 设备详情
     */
    @Select("SELECT d.*, e.name as employee_name, e.employee_number, e.employee_type FROM device_management d LEFT JOIN employee e ON d.employee_id = e.id WHERE d.id = #{id}")
    @Results({
        @Result(property = "id", column = "id"),
        @Result(property = "employee", column = "employee_id", one = @One(select = "com.ruanzhu.doorhandle.module.device.mapper.EmployeeMapper.selectById"))
    })
    Device getDeviceWithEmployee(Long id);

    /**
     * 获取所有设备列表，包括关联的员工信息
     * @return 设备列表
     */
    @Select("SELECT d.*, e.name as employee_name, e.employee_number FROM device_management d LEFT JOIN employee e ON d.employee_id = e.id")
    @Results({
        @Result(property = "id", column = "id"),
        @Result(property = "employee", column = "employee_id", one = @One(select = "com.ruanzhu.doorhandle.module.device.mapper.EmployeeMapper.selectById"))
    })
    List<Device> findAllWithEmployee();
} 