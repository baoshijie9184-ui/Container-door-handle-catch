package com.ruanzhu.doorhandle.contracts.detection;

import lombok.Builder;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

@Data
@Builder
@lombok.NoArgsConstructor
@lombok.AllArgsConstructor
public class DetectionTaskCreatedEvent {
    private String eventId;
    private String eventType;
    private String eventTime;
    private String taskId;
    private String dispatchId;
    private String bucketName;
    private String sourcePrefix;
    private List<String> originalKeys;
    private DetectionTaskEventCaptureInfo captureInfo;
    private Integer modelId;
    private BigDecimal threshold;
}
