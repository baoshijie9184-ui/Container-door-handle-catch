package com.ruanzhu.doorhandle.module.system.entity;

import lombok.Data;

/** A projection of the account's association fields, never an independently inserted row. */
@Data
public class AccountEmployeeBinding {
    private Long userId;
    private Long employeeId;
    private Integer version;
}
