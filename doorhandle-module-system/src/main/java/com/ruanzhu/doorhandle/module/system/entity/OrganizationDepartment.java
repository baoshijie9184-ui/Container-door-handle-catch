package com.ruanzhu.doorhandle.module.system.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

@Data
@TableName("organization_department")
public class OrganizationDepartment {
    @TableId(type = IdType.AUTO) private Long id;
    private String name;
}
