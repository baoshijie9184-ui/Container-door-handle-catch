package com.ruanzhu.doorhandle.module.detection.dto.detection;

import lombok.Builder;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

@Data
@Builder
public class RemoteDetectionTaskRequest {
    private String taskId;
    private String bucketName;
    private String sourcePrefix;
    private DetectionCaptureInfo captureInfo;
    private List<String> originalKeys;
    private Integer modelId;
    private BigDecimal threshold;
}
