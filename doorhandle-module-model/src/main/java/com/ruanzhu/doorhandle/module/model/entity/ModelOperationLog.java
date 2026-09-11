package com.ruanzhu.doorhandle.module.model.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("model_operation_log")
public class ModelOperationLog {

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    @TableField("model_id")
    private Integer modelId;

    @TableField("operation_type")
    private String operationType;

    @TableField("operator")
    private String operator;

    @TableField("operation_time")
    private LocalDateTime operationTime;

    @TableField("remark")
    private String remark;
}
