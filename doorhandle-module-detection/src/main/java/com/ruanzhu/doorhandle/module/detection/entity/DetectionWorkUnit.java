package com.ruanzhu.doorhandle.module.detection.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import java.time.LocalDateTime;

@Data
@TableName("detection_work_unit")
public class DetectionWorkUnit {
    @TableId(type = IdType.AUTO) private Long id;
    private String workUnitId;
    private String sourceBatchId;
    private String applicantUserId;
    private String assigneeUserId;
    private Integer imageCount;
    private Integer completedCount;
    private String strategy;
    private String status;
    private String modelVersion;
    private Integer version;
    private String remark;
    private LocalDateTime submittedAt;
    private LocalDateTime assignedAt;
    private LocalDateTime completedAt;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
