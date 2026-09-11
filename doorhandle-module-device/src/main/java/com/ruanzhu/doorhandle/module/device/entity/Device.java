package com.ruanzhu.doorhandle.module.device.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.annotation.Version;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 设备实体类
 */
@Data
@TableName("device_management")
public class Device {
    /** 乐观锁版本，避免设备状态和负责人被并发覆盖。 */
    @Version
    @TableField("version")
    private Integer version;
    /**
     * 设备ID
     */
    @TableId(value = "id", type = IdType.AUTO)
    private Long id;
    
    /**
     * 设备编号
     */
    @TableField("device_code")
    private String deviceCode;
    
    /**
     * 设备类型
     */
    @TableField("device_type")
    private String deviceType;
    
    /**
     * 设备型号
     */
    @TableField("model_name")
    private String modelName;
    
    /**
     * 序列号
     */
    @TableField("serial_number")
    private String serialNumber;
    
    /**
     * 设备状态: IN_USE-使用中, MAINTENANCE-维护中, IDLE-未使用, OFFLINE-离线
     */
    @TableField("status")
    private String status;

    /**
     * 在线状态: ONLINE-在线, OFFLINE-离线
     */
    @TableField("online_status")
    private String onlineStatus;

    /**
     * 最近心跳时间
     */
    @TableField("last_heartbeat_at")
    private LocalDateTime lastHeartbeatAt;

    @TableField("station_code")
    private String stationCode;

    @TableField("edge_node_id")
    private String edgeNodeId;

    @TableField("plc_status")
    private String plcStatus;

    @TableField("camera_status")
    private String cameraStatus;

    @TableField("capture_status")
    private String captureStatus;

    @TableField("last_image_key")
    private String lastImageKey;

    @TableField("last_capture_at")
    private LocalDateTime lastCaptureAt;

    @TableField("runtime_metadata_json")
    private String runtimeMetadataJson;
    
    /**
     * 最近维护日期
     */
    @TableField("last_maintenance_date")
    private LocalDateTime lastMaintenanceDate;
    
    /**
     * 关联员工ID
     */
    @TableField("employee_id")
    private Long employeeId;
    
    /**
     * 关联员工信息（非数据库字段）
     */
    @TableField(exist = false)
    private Employee employee;
    
    /**
     * 创建时间
     */
    @TableField("created_at")
    private LocalDateTime createdTime;
    
    /**
     * 更新时间
     */
    @TableField("updated_at")
    private LocalDateTime updatedTime;
} 
