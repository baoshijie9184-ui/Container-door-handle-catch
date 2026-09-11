package com.ruanzhu.doorhandle.module.detection.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import java.time.LocalDateTime;

@Data
@TableName("detection_work_unit_image")
public class DetectionWorkUnitImage {
    @TableId(type = IdType.AUTO) private Long id;
    private String workUnitId;
    private String imageId;
    private String fileName;
    private String sha256;
    private String objectKey;
    private String status;
    private String detectionRunId;
    private Integer version;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
