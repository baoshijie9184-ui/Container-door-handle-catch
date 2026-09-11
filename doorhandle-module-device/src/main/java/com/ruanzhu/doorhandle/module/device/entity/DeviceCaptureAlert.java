package com.ruanzhu.doorhandle.module.device.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("device_capture_alert")
public class DeviceCaptureAlert {
    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    @TableField("alert_id")
    private String alertId;

    @TableField("device_id")
    private Long deviceId;

    @TableField("device_code")
    private String deviceCode;

    @TableField("device_type")
    private String deviceType;

    @TableField("station_code")
    private String stationCode;

    @TableField("edge_node_id")
    private String edgeNodeId;

    @TableField("alert_type")
    private String alertType;

    @TableField("alert_level")
    private String alertLevel;

    @TableField("alert_message")
    private String alertMessage;

    @TableField("runtime_snapshot_json")
    private String runtimeSnapshotJson;

    @TableField("status")
    private String status;

    @TableField("ack_operator")
    private String ackOperator;

    @TableField("ack_remark")
    private String ackRemark;

    @TableField("acknowledged_at")
    private LocalDateTime acknowledgedAt;

    @TableField("resolved_operator")
    private String resolvedOperator;

    @TableField("resolved_remark")
    private String resolvedRemark;

    @TableField("resolved_at")
    private LocalDateTime resolvedAt;

    @TableField("created_at")
    private LocalDateTime createdAt;

    @TableField("updated_at")
    private LocalDateTime updatedAt;
}
