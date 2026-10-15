package com.ruanzhu.doorhandle.module.system.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

@Data
@TableName("account_employee_binding")
public class AccountEmployeeBinding {
    @TableId(value = "user_id", type = IdType.INPUT) private Long userId;
    @TableField(updateStrategy = FieldStrategy.ALWAYS) private Long employeeId;
    private Integer version;
}
