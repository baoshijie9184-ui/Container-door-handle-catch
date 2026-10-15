package com.ruanzhu.doorhandle.contracts.organization;

import java.util.Collection;
import java.util.List;

/** 员工身份由设备模块提供；调用方不穿透员工实体或 Mapper。 */
public interface EmployeeDirectoryApi {
    record EmployeeIdentity(Long id, String employeeNumber, String name, String status,
                            String employeeType, Long departmentId, String departmentName) {}
    List<EmployeeIdentity> findAll(Collection<Long> ids);
    /** 在调用方的单体数据库事务中锁定员工，避免绑定与删除、调岗竞态。 */
    EmployeeIdentity lock(Long id);
}
