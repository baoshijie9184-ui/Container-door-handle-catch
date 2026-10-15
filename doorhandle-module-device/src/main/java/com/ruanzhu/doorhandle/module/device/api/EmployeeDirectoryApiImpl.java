package com.ruanzhu.doorhandle.module.device.api;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.organization.EmployeeDirectoryApi;
import com.ruanzhu.doorhandle.module.device.entity.Employee;
import com.ruanzhu.doorhandle.module.device.mapper.EmployeeMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import java.util.Collection;
import java.util.List;

@Service
public class EmployeeDirectoryApiImpl implements EmployeeDirectoryApi {
    private final EmployeeMapper employees;
    public EmployeeDirectoryApiImpl(EmployeeMapper employees) { this.employees = employees; }
    public List<EmployeeIdentity> findAll(Collection<Long> ids) {
        if (ids.isEmpty()) return List.of();
        if (ids.size() > 100) throw new IllegalArgumentException("员工查询最多 100 项");
        return employees.selectBatchIds(ids).stream().map(EmployeeDirectoryApiImpl::identity).toList();
    }
    public EmployeeIdentity lock(Long id) {
        if (!TransactionSynchronizationManager.isActualTransactionActive()) throw new IllegalStateException("锁定员工必须在事务中执行");
        var employee = employees.selectOne(new LambdaQueryWrapper<Employee>().eq(Employee::getId, id).last("FOR UPDATE"));
        if (employee == null) throw new BusinessException(404, "员工不存在");
        return identity(employee);
    }
    private static EmployeeIdentity identity(Employee e) {
        return new EmployeeIdentity(e.getId(), e.getEmployeeNumber(), e.getName(), e.getStatus(), e.getEmployeeType(), e.getDepartmentId(), e.getDepartment());
    }
}
