package com.ruanzhu.doorhandle.module.device.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 设备使用记录实体类
 *
 * 注意：device_code/device_type/model_name/serial_number 和
 * employee_name/employee_number/contact 为历史快照字段。
 * 当设备或员工信息变更时，历史记录保留创建时的数据快照，
 * 用于审计追溯。当前数据通过 device_id/employee_id 关联查询。
 */
@Data
@NoArgsConstructor
@TableName("device_usage_record")
public class DeviceUsageRecord {

    /** 主键ID */
    @TableId(type = IdType.AUTO)
    private Long id;

    /** 设备ID（外键 -> device_management.id） */
    @TableField("device_id")
    private Long deviceId;

    /** 设备编号（快照字段，创建时从 device_management 复制） */
    @TableField("device_code")
    private String deviceCode;

    /** 设备类型（快照字段） */
    @TableField("device_type")
    private String deviceType;

    /** 设备型号（快照字段） */
    @TableField("model_name")
    private String modelName;

    /** 设备序列号（快照字段） */
    @TableField("serial_number")
    private String serialNumber;

    /** 员工ID（外键 -> employee.id） */
    @TableField("employee_id")
    private Long employeeId;

    /** 员工姓名（快照字段，创建时从 employee 复制） */
    @TableField("employee_name")
    private String employeeName;

    /** 员工编号（快照字段） */
    @TableField("employee_number")
    private String employeeNumber;

    /** 联系方式（快照字段） */
    @TableField("contact")
    private String contact;

    /** 使用开始时间 */
    @TableField("start_time")
    private LocalDateTime startTime;

    /** 使用结束时间 */
    @TableField("end_time")
    private LocalDateTime endTime;

    /**
     * 记录状态: IN_USE-使用中, RETURNED-已归还
     */
    @TableField("status")
    private String status;

    /** 备注 */
    @TableField("remarks")
    private String remarks;

    /** 创建时间 */
    @TableField("created_at")
    private LocalDateTime createdTime;

    /** 更新时间 */
    @TableField("updated_at")
    private LocalDateTime updatedTime;
}
