package com.ruanzhu.doorhandle.module.device.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.annotation.Version;
import lombok.Data;

import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 * 员工实体类
 */
@Data
@TableName("employee")
public class Employee {

    /** 乐观锁版本，主管并发编辑时版本不一致将拒绝覆盖。 */
    @Version
    @TableField("version")
    private Integer version;

    /** 员工ID */
    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    /** 姓名 */
    @TableField("name")
    private String name;

    /** 员工编号 */
    @TableField("employee_number")
    private String employeeNumber;

    /** 联系方式 */
    @TableField("contact")
    private String contact;

    /** 性别 */
    @TableField("gender")
    private String gender;

    /** 所属部门/班组 */
    @TableField("department")
    private String department;

    /**
     * 员工类型：DETECTION-门把手检测人员，COLLECTION-门把手图片采集人员，MAINTENANCE-设备维修人员
     */
    @TableField("employee_type")
    private String employeeType;

    /**
     * 员工状态：ACTIVE-在岗，RESIGNED-离职，VACATION-休假
     */
    @TableField("status")
    private String status;

    /** 入职日期 */
    @TableField("hire_date")
    private LocalDate hireDate;

    /** 备注（非数据库字段） */
    @TableField(exist = false)
    private String remark;

    /** 创建时间 */
    @TableField("created_at")
    private LocalDateTime createdTime;

    /** 更新时间 */
    @TableField("updated_at")
    private LocalDateTime updatedTime;
}
