package com.ruanzhu.doorhandle.module.device.service;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.IService;
import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.entity.Employee;

import java.util.List;

/**
 * 员工服务接口
 */
public interface EmployeeService extends IService<Employee> {
    
    /**
     * 分页查询员工列表
     * @param page 页码
     * @param size 每页大小
     * @param name 姓名（可选）
     * @param employeeNumber 员工编号（可选）
     * @param contact 联系方式（可选）
     * @param department 部门/班组（可选）
     * @param employeeType 员工类型（可选）
     * @param status 状态（可选）
     * @return 分页结果
     */
    Page<Employee> findByPage(int page, int size, String name, String employeeNumber, String contact, 
                             String department, String employeeType, String status);
    
    /**
     * 根据ID获取员工详情
     * @param id 员工ID
     * @return 员工信息
     */
    Employee getById(Long id);
    
    /**
     * 根据员工类型查询在职员工
     * @param employeeType 员工类型
     * @return 员工列表
     */
    List<Employee> findByEmployeeType(String employeeType);
    
    /**
     * 查询设备的员工
     * @param deviceId 设备ID
     * @return 员工信息
     */
    Employee getByDeviceId(Long deviceId);
    
    /**
     * 获取员工分配的设备列表
     * @param employeeId 员工ID
     * @return 设备列表
     */
    List<Device> getDevicesByEmployeeId(Long employeeId);
    
    /**
     * 新增员工
     * @param employee 员工信息
     * @return 是否成功
     */
    boolean add(Employee employee);
    
    /**
     * 更新员工信息
     * @param employee 员工信息
     * @return 是否成功
     */
    boolean update(Employee employee);
    
    /**
     * 删除员工
     * @param id 员工ID
     * @return 是否成功
     */
    boolean delete(Long id);
    
    /**
     * 分配设备给员工
     * @param employeeId 员工ID
     * @param deviceId 设备ID
     * @return 是否成功
     */
    boolean assignDeviceToEmployee(Long employeeId, Long deviceId);
    
    /**
     * 解除设备分配
     * @param deviceId 设备ID
     * @return 是否成功
     */
    boolean unassignDevice(Long deviceId);

    /**
     * 获取员工统计信息
     * @return 包含各类型员工数量的统计Map
     */
    java.util.Map<String, Object> getEmployeeStats();

    /**
     * 检查员工编号是否已存在
     */
    boolean existsByEmployeeNumber(String employeeNumber, Long excludeId);
}