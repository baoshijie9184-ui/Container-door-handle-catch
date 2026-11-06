package com.ruanzhu.doorhandle.module.detection.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import java.time.LocalDateTime;

@Data
@TableName("detection_input")
public class DetectionWorkUnitImage {
    @TableId(type = IdType.AUTO) private Long id;
    private String workUnitId;
    private String imageId;
    private String fileName;
    private String sha256;
    private String objectKey;
    private String status;
    private String detectionRunId;
    /** Optional verified shared content reference; legacy rows keep their original object key. */
    private String contentAssetId;
    private Integer contentVersion;
    private Integer version;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
