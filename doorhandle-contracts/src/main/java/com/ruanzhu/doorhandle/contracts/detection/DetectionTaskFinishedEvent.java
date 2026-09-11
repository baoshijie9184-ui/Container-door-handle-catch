package com.ruanzhu.doorhandle.contracts.detection;

import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import lombok.AllArgsConstructor;

import java.util.List;
import java.util.Map;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class DetectionTaskFinishedEvent {
    private String eventId;
    private String eventType;
    private String eventTime;
    private String taskId;
    private String dispatchId;
    private String status;
    private String resultOssPrefix;
    private String resultJsonKey;
    private List<String> previewKeys;
    private Map<String, Object> statistics;
    private List<Map<String, Object>> defectEvidence;
    private Integer totalImages;
    private Integer successfulImages;
    private Integer failedImages;
    private String errorMessage;
    private String startedAt;
    private String finishedAt;
}
