package com.ruanzhu.doorhandle.module.system.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;
import java.time.LocalDateTime;

@Data
@TableName("organization_binding_audit")
public class OrganizationBindingAudit {
    @TableId(type = IdType.AUTO) private Long id;
    private Long userId;
    private String username;
    private Long actorUserId;
    private String actorUsername;
    private Long beforeEmployeeId;
    private Long afterEmployeeId;
    private Integer bindingVersion;
    private String action;
    private LocalDateTime createdAt;
}
