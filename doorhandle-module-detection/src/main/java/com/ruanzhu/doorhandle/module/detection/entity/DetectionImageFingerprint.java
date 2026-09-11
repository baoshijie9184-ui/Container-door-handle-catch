package com.ruanzhu.doorhandle.module.detection.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("detection_image_fingerprint")
public class DetectionImageFingerprint {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String sha256;
    private String fileName;
    private String objectKey;
    private String status;
    private String lastTaskId;
    private String ownerUserId;
    private Integer version;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
