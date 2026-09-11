package com.ruanzhu.doorhandle.module.detection.dto.detection;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class DetectionTraceEvent {
    private String eventType;
    private String eventName;
    private String occurredAt;
    private String operator;
    private String description;
}
