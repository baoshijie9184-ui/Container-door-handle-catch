package com.ruanzhu.doorhandle.module.system.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.organization.OrganizationDirectoryApi;
import com.ruanzhu.doorhandle.module.system.entity.*;
import com.ruanzhu.doorhandle.module.system.mapper.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.util.List;

@Service
public class OrganizationDepartmentService implements OrganizationDirectoryApi {
    private final OrganizationDepartmentMapper departments;
    private final AccountEmployeeBindingMapper bindings;
    public OrganizationDepartmentService(OrganizationDepartmentMapper departments, AccountEmployeeBindingMapper bindings) {
        this.departments = departments; this.bindings = bindings;
    }
    public List<DepartmentIdentity> list() {
        return departments.selectList(new LambdaQueryWrapper<OrganizationDepartment>().orderByAsc(OrganizationDepartment::getId))
                .stream().map(d -> new DepartmentIdentity(d.getId(), d.getName())).toList();
    }
    @Transactional
    public DepartmentIdentity create(String name) {
        if (name == null || name.isBlank() || name.trim().length() > 100) throw new BusinessException(400, "部门名称为 1 到 100 个字符");
        String normalized = name.trim();
        if (departments.selectCount(new LambdaQueryWrapper<OrganizationDepartment>().eq(OrganizationDepartment::getName, normalized)) > 0)
            throw new BusinessException(409, "部门名称已存在");
        var department = new OrganizationDepartment(); department.setName(normalized);
        departments.insert(department);
        return new DepartmentIdentity(department.getId(), department.getName());
    }
    public DepartmentIdentity requireDepartment(Long id, String legacyName) {
        OrganizationDepartment department = id == null ?
                (legacyName == null || legacyName.isBlank() ? null : departments.selectOne(
                        new LambdaQueryWrapper<OrganizationDepartment>().eq(OrganizationDepartment::getName, legacyName.trim()))) : departments.selectById(id);
        if (department == null) throw new BusinessException(400, "请选择已有部门；新部门请先在账号与组织中创建");
        return new DepartmentIdentity(department.getId(), department.getName());
    }
    public void assertEmployeeUnbound(Long employeeId) {
        if (bindings.selectCount(new LambdaQueryWrapper<AccountEmployeeBinding>().eq(AccountEmployeeBinding::getEmployeeId, employeeId)) > 0)
            throw new BusinessException(409, "员工已关联登录账号，请先解除账号关联再删除");
    }
}
