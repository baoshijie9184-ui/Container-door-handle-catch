package com.ruanzhu.doorhandle.module.infra.entity;

import lombok.Data;

import java.time.LocalDateTime;

/** Typed infrastructure audit input; deliberately not mapped to a separate table. */
@Data
public class OperationAuditLog {
    private Long id;
    private String operator;
    private String action;
    private String resourceType;
    private String resourceId;
    private String requestMethod;
    private String requestPath;
    private String changeSummary;
    private String result;
    private String clientIp;
    private LocalDateTime createdAt;
}
