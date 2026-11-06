package com.ruanzhu.doorhandle.module.system.entity;

import lombok.Data;
import java.time.LocalDateTime;

@Data
public class OrganizationBindingAudit {
    private Long id;
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
