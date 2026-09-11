package com.ruanzhu.doorhandle.module.device.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.entity.Employee;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 员工Mapper接口
 */
@Mapper
public interface EmployeeMapper extends BaseMapper<Employee> {
    
    /**
     * 根据员工类型查询在岗员工
     * @param employeeType 员工类型
     * @return 员工列表
     */
    @Select("SELECT * FROM employee WHERE employee_type = #{employeeType} AND status = 'ACTIVE'")
    List<Employee> findByEmployeeType(String employeeType);
    
    /**
     * 根据设备ID查询使用该设备的员工
     * @param deviceId 设备ID
     * @return 员工信息
     */
    @Select("SELECT e.* FROM employee e INNER JOIN device_management d ON e.id = d.employee_id WHERE d.id = #{deviceId}")
    Employee getByDeviceId(Long deviceId);
    
    /**
     * 获取员工分配的设备列表
     * @param employeeId 员工ID
     * @return 设备列表
     */
    @Select("SELECT * FROM device_management WHERE employee_id = #{employeeId}")
    List<Device> getDevicesByEmployeeId(Long employeeId);
} 