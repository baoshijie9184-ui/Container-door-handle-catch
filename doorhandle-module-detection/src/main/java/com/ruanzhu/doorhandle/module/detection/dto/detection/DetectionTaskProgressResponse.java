package com.ruanzhu.doorhandle.module.detection.dto.detection;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class DetectionTaskProgressResponse {
    private String taskId;
    private String workflowUuid;
    private String status;
    private String stage;
    private String batchNo;
    private String workOrderNo;
    private String flowStatus;
    /** Business-state hints only; execution still rechecks current account and task permissions. */
    private java.util.List<DetectionQualityAction> qualityActions;
    private String qualityStation;
    private String assignee;
    private Long assignmentRevision;
    private String assignmentRemark;
    private String assignedAt;
    private String dueAt;
    private Integer progressPercent;
    private Integer totalImages;
    private Integer processedImages;
    private Integer successfulImages;
    private Integer failedImages;
    private Integer defectCount;
    private String primaryDefectType;
    private String maxDefectSeverity;
    private String message;
    private String createdAt;
    private String updatedAt;
    private String finishedAt;
    private String folderName;
    private String errorMessage;
    private String reviewStatus;
    private String reviewConclusion;
    private String severityLevel;
    private Integer confirmedDefectCount;
    private Integer falsePositiveCount;
    private String reviewRemark;
    private String reviewer;
    private String reviewedAt;
    private String dispositionStatus;
    private String dispositionAction;
    private String dispositionRemark;
    private String dispositionOperator;
    private String disposedAt;
    private Boolean recheckRequired;
    private String reworkResult;
    private String reworkOperator;
    private String reworkRemark;
    private String reworkCompletedAt;
    private String captureDate;
    private String region;
    private String collector;
    private String deviceName;
    private String imageFolderName;
    private String sourceOssPrefix;
}
