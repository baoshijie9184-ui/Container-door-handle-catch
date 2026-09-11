package com.ruanzhu.doorhandle.module.detection.dto.detection;

import lombok.Data;

import java.util.List;
import java.util.Map;

@Data
public class RemoteDetectionTaskResponse {
    private String taskId;
    private String status;
    private Integer totalImages;
    private Integer successfulImages;
    private Integer failedImages;
    private Map<String, Object> statistics;
    private List<Map<String, Object>> defectEvidence;
    private List<String> previewKeys;
    private String resultJsonKey;
    private String resultOssPrefix;
    private String errorMessage;
}
