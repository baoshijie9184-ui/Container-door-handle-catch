package com.ruanzhu.doorhandle.module.device.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.StringUtils;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.entity.Employee;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceMapper;
import com.ruanzhu.doorhandle.module.device.mapper.EmployeeMapper;
import com.ruanzhu.doorhandle.module.device.service.DeviceUsageRecordService;
import com.ruanzhu.doorhandle.module.device.service.EmployeeService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 员工服务实现类
 */
@Service
public class EmployeeServiceImpl extends ServiceImpl<EmployeeMapper, Employee> implements EmployeeService {
    
    @Autowired
    private EmployeeMapper employeeMapper;
    
    @Autowired
    private DeviceMapper deviceMapper;
    
    @Autowired
    private DeviceUsageRecordService deviceUsageRecordService;

    @Autowired
    private com.ruanzhu.doorhandle.contracts.organization.OrganizationDirectoryApi organization;
    
    @Override
    public Page<Employee> findByPage(int page, int size, String name, String employeeNumber, String contact, 
                                    String department, String employeeType, String status) {
        Page<Employee> pageInfo = new Page<>(page, size);
        LambdaQueryWrapper<Employee> queryWrapper = new LambdaQueryWrapper<>();
        
        // 添加查询条件
        if (StringUtils.isNotBlank(name)) {
            queryWrapper.like(Employee::getName, name);
        }
        if (StringUtils.isNotBlank(employeeNumber)) {
            queryWrapper.like(Employee::getEmployeeNumber, employeeNumber);
        }
        if (StringUtils.isNotBlank(contact)) {
            queryWrapper.like(Employee::getContact, contact);
        }
        if (StringUtils.isNotBlank(department)) {
            queryWrapper.like(Employee::getDepartment, department);
        }
        if (StringUtils.isNotBlank(employeeType)) {
            queryWrapper.eq(Employee::getEmployeeType, employeeType);
        }
        if (StringUtils.isNotBlank(status)) {
            queryWrapper.eq(Employee::getStatus, status);
        }
        
        // 按更新时间降序排序
        queryWrapper.orderByDesc(Employee::getUpdatedTime);
        
        return page(pageInfo, queryWrapper);
    }
    
    @Override
    public Employee getById(Long id) {
        return employeeMapper.selectById(id);
    }
    
    @Override
    public List<Employee> findByEmployeeType(String employeeType) {
        return employeeMapper.findByEmployeeType(employeeType);
    }
    
    @Override
    public Employee getByDeviceId(Long deviceId) {
        return employeeMapper.getByDeviceId(deviceId);
    }
    
    @Override
    @Transactional(rollbackFor = Exception.class)
    public List<Device> getDevicesByEmployeeId(Long employeeId) {
        // 验证员工是否存在
        Employee employee = getById(employeeId);
        if (employee == null) {
            return List.of();
        }
        
        // 获取员工关联的设备列表
        return deviceMapper.findByEmployeeId(employeeId);
    }
    
    @Override
    @Transactional(rollbackFor = Exception.class)
    @CacheEvict(cacheNames = {"employee", "device", "dashboard"}, allEntries = true)
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="EMPLOYEE",action="add",resource="arg0.id",version="arg0.version",supervisorOnly=true)
    public boolean add(Employee employee) {
        normalizeDepartment(employee);
        // 设置创建时间和更新时间
        LocalDateTime now = LocalDateTime.now();
        employee.setCreatedTime(now);
        employee.setUpdatedTime(now);
        
        return save(employee);
    }
    
    @Override
    @Transactional(rollbackFor = Exception.class)
    @CacheEvict(cacheNames = {"employee", "device", "dashboard"}, allEntries = true)
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="EMPLOYEE",action="update",resource="arg0.id",version="arg0.version",supervisorOnly=true)
    public boolean update(Employee employee) {
        if (employee == null || employee.getId() == null) {
            throw new com.ruanzhu.doorhandle.common.BusinessException(400, "员工编号不能为空");
        }
        Employee existing = employeeMapper.selectById(employee.getId());
        if (existing == null) {
            throw new com.ruanzhu.doorhandle.common.BusinessException(404, "员工不存在");
        }
        if (employee.getDepartmentId() == null && employee.getDepartment() == null) {
            employee.setDepartmentId(existing.getDepartmentId());
            employee.setDepartment(existing.getDepartment());
        }
        normalizeDepartment(employee);
        if (employee.getStatus() != null && !"ACTIVE".equals(employee.getStatus())
                && !deviceMapper.findByEmployeeId(employee.getId()).isEmpty()) {
            throw new com.ruanzhu.doorhandle.common.BusinessException(409, "员工仍有分配设备，请先完成设备归还");
        }
        // 设置更新时间
        employee.setUpdatedTime(LocalDateTime.now());
        
        if (employee.getVersion() == null) {
            throw new com.ruanzhu.doorhandle.common.BusinessException(400, "更新员工必须提供版本号");
        }
        if (!updateById(employee)) {
            throw new com.ruanzhu.doorhandle.common.BusinessException(409, "员工资料已被其他主管更新，请刷新后重试");
        }
        return true;
    }
    
    @Override
    @Transactional(rollbackFor = Exception.class)
    @CacheEvict(cacheNames = {"employee", "device", "dashboard"}, allEntries = true)
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="EMPLOYEE",action="delete",supervisorOnly=true)
    public boolean delete(Long id) {
        // 与绑定使用同一员工行锁；外键是竞态下的最后一道保护。
        employeeMapper.selectOne(new LambdaQueryWrapper<Employee>().eq(Employee::getId, id).last("FOR UPDATE"));
        organization.assertEmployeeUnbound(id);
        // 先解除该员工关联的所有设备
        deviceMapper.removeEmployeeFromDevices(id);
        
        // 再删除员工
        return removeById(id);
    }

    private void normalizeDepartment(Employee employee) {
        var department = organization.requireDepartment(employee.getDepartmentId(), employee.getDepartment());
        employee.setDepartmentId(department.id());
        employee.setDepartment(department.name());
    }
    
    @Override
    @Transactional(rollbackFor = Exception.class)
    @CacheEvict(cacheNames = {"employee", "device", "dashboard"}, allEntries = true)
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="EMPLOYEE",action="assignDeviceToEmployee",supervisorOnly=true)
    public boolean assignDeviceToEmployee(Long employeeId, Long deviceId) {
        // 验证员工和设备是否存在
        Employee employee = getById(employeeId);
        Device device = deviceMapper.selectById(deviceId);
        
        if (employee == null || device == null) {
            return false;
        }
        if (!"ACTIVE".equals(employee.getStatus())) {
            throw new com.ruanzhu.doorhandle.common.BusinessException(400, "休假或离职员工不能分配设备");
        }
        
        // 检查设备是否已分配给其他员工
        if (device.getEmployeeId() != null) {
            return false;
        }
        
        // 实现业务规则：
        // 1. 检测设备(DETECTION)只能分配给图片检测人员(DETECTION)或维修人员(MAINTENANCE)
        // 2. 采集设备(IMAGE_CAPTURE)只能分配给图片采集人员(COLLECTION)或维修人员(MAINTENANCE)
        String employeeType = employee.getEmployeeType();
        String deviceType = device.getDeviceType();
        
        if ("DETECTION".equals(deviceType) && 
            !("DETECTION".equals(employeeType) || "MAINTENANCE".equals(employeeType))) {
            // 检测设备只能分配给检测人员或维修人员
            return false;
        }
        
        if ("IMAGE_CAPTURE".equals(deviceType) && 
            !("COLLECTION".equals(employeeType) || "MAINTENANCE".equals(employeeType))) {
            // 采集设备只能分配给采集人员或维修人员
            return false;
        }
        
        // 根据员工类型设置设备状态
        String newStatus;
        if ("MAINTENANCE".equals(employee.getEmployeeType())) {
            // 维修人员
            newStatus = "MAINTENANCE";
        } else {
            // 检测人员或采集人员
            newStatus = "IN_USE";
        }
        
        // 更新设备状态
        device.setEmployeeId(employeeId);
        device.setStatus(newStatus);
        device.setUpdatedTime(LocalDateTime.now());
        
        // 分配设备给员工并更新状态
        boolean result = deviceMapper.updateById(device) > 0;
        if (!result) {
            throw new com.ruanzhu.doorhandle.common.BusinessException(409, "设备已被其他主管分配，请刷新后重试");
        }
        
        // 创建设备使用记录
        if (result) {
            String remarks = "设备分配给员工";
            if ("MAINTENANCE".equals(employee.getEmployeeType())) {
                remarks = "设备分配给维修人员进行维护";
            } else if ("DETECTION".equals(employee.getEmployeeType())) {
                remarks = "设备分配给检测人员进行使用";
            } else if ("COLLECTION".equals(employee.getEmployeeType())) {
                remarks = "设备分配给采集人员进行使用";
            }
            
            deviceUsageRecordService.createRecordOnAssign(deviceId, employeeId, remarks);
        }
        
        return result;
    }
    
    @Override
    @Transactional(rollbackFor = Exception.class)
    @CacheEvict(cacheNames = {"employee", "device", "dashboard"}, allEntries = true)
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DEVICE",action="UNASSIGN_EMPLOYEE",supervisorOnly=true)
    public boolean unassignDevice(Long deviceId) {
        // 检查设备是否存在
        Device device = deviceMapper.selectById(deviceId);
        if (device == null) {
            return false;
        }
        
        // 如果设备没有关联员工，直接返回成功
        if (device.getEmployeeId() == null) {
            return true;
        }
        
        // 更新设备状态为 IDLE 并解除关联
        device.setEmployeeId(null);
        device.setStatus("IDLE");
        device.setUpdatedTime(LocalDateTime.now());
        
        boolean result = deviceMapper.updateById(device) > 0;
        if (!result) {
            throw new com.ruanzhu.doorhandle.common.BusinessException(409, "设备已被其他主管修改，请刷新后重试");
        }
        
        // 更新设备使用记录
        if (result) {
            deviceUsageRecordService.updateRecordOnUnassign(deviceId, "设备已归还");
        }

        return result;
    }

    @Override
    @Cacheable(cacheNames = "employee", key = "'stats'")
    public Map<String, Object> getEmployeeStats() {
        Map<String, Object> stats = new HashMap<>();

        // 总员工数
        long total = count();
        stats.put("total", total);

        // 各类型员工数量
        LambdaQueryWrapper<Employee> collectionWrapper = new LambdaQueryWrapper<>();
        collectionWrapper.eq(Employee::getEmployeeType, "COLLECTION");
        long collection = count(collectionWrapper);
        stats.put("collection", collection);

        LambdaQueryWrapper<Employee> detectionWrapper = new LambdaQueryWrapper<>();
        detectionWrapper.eq(Employee::getEmployeeType, "DETECTION");
        long detection = count(detectionWrapper);
        stats.put("detection", detection);

        LambdaQueryWrapper<Employee> maintenanceWrapper = new LambdaQueryWrapper<>();
        maintenanceWrapper.eq(Employee::getEmployeeType, "MAINTENANCE");
        long maintenance = count(maintenanceWrapper);
        stats.put("maintenance", maintenance);

        // 在职员工数
        LambdaQueryWrapper<Employee> activeWrapper = new LambdaQueryWrapper<>();
        activeWrapper.eq(Employee::getStatus, "ACTIVE");
        long active = count(activeWrapper);
        stats.put("active", active);

        // 休假员工数
        LambdaQueryWrapper<Employee> vacationWrapper = new LambdaQueryWrapper<>();
        vacationWrapper.eq(Employee::getStatus, "VACATION");
        long vacation = count(vacationWrapper);
        stats.put("vacation", vacation);

        // 离职员工数
        LambdaQueryWrapper<Employee> resignedWrapper = new LambdaQueryWrapper<>();
        resignedWrapper.eq(Employee::getStatus, "RESIGNED");
        long resigned = count(resignedWrapper);
        stats.put("resigned", resigned);

        return stats;
    }

    @Override
    public boolean existsByEmployeeNumber(String employeeNumber, Long excludeId) {
        LambdaQueryWrapper<Employee> wrapper = new LambdaQueryWrapper<Employee>()
                .eq(Employee::getEmployeeNumber, employeeNumber);
        if (excludeId != null) {
            wrapper.ne(Employee::getId, excludeId);
        }
        return count(wrapper) > 0;
    }
}
