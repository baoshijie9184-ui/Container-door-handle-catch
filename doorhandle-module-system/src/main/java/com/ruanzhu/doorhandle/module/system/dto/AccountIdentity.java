package com.ruanzhu.doorhandle.module.system.dto;

/** 白名单身份响应，不包含密码、手机、邮箱或 Token。 */
public record AccountIdentity(Long userId, String username, String role, Long employeeId,
        String employeeNumber, String employeeName, String employeeStatus, String employeeType,
        Long departmentId, String departmentName, int bindingVersion, String dataScope) {}
