package com.ruanzhu.doorhandle.module.detection.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import java.time.LocalDateTime;

@Data
@TableName("detection_duplicate_ticket")
public class DetectionDuplicateTicket {
    @TableId(type = IdType.AUTO) private Long id;
    private String ticketId;
    private String sha256;
    private String leftTaskId;
    private String rightTaskId;
    private String leftEmployeeId;
    private String rightEmployeeId;
    private String leftFolderName;
    private String rightFolderName;
    private String leftImagesJson;
    private String rightImagesJson;
    private String assignedTo;
    private String comparisonResult;
    private String resolution;
    private String status;
    private String approvedBy;
    private LocalDateTime approvedAt;
    private Integer version;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
