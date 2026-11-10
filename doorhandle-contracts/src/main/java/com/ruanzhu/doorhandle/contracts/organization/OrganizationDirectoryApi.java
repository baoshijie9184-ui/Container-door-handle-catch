package com.ruanzhu.doorhandle.contracts.organization;

/** 组织主数据由系统模块维护。部门创建后名称和 ID 保持稳定。 */
public interface OrganizationDirectoryApi {
    record DepartmentIdentity(Long id, String name, Long version) {
        /** Older callers have no observed revision; unknown must not become a fabricated zero. */
        public DepartmentIdentity(Long id, String name) { this(id,name,null); }
    }
    DepartmentIdentity requireDepartment(Long id, String legacyName);
    void assertEmployeeUnbound(Long employeeId);
}
