package com.ruanzhu.doorhandle.module.detection.dto.detection;

import lombok.Data;

@Data
public class DetectionTaskAssignmentRequest {
    private String qualityStation;
    private String assignee;
    private String dueAt;
    private String assignmentRemark;
}
