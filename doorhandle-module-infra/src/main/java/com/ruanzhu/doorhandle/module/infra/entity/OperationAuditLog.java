package com.ruanzhu.doorhandle.module.infra.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("operation_audit_log")
public class OperationAuditLog {
    @TableId(value = "id", type = IdType.AUTO)
    private Long id;
    private String operator;
    private String action;
    @TableField("resource_type")
    private String resourceType;
    @TableField("resource_id")
    private String resourceId;
    @TableField("request_method")
    private String requestMethod;
    @TableField("request_path")
    private String requestPath;
    @TableField("change_summary")
    private String changeSummary;
    private String result;
    @TableField("client_ip")
    private String clientIp;
    @TableField("created_at")
    private LocalDateTime createdAt;
}
