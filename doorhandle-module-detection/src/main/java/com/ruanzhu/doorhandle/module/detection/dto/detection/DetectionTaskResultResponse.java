package com.ruanzhu.doorhandle.module.detection.dto.detection;

import lombok.Builder;
import lombok.Data;

import java.util.List;
import java.util.Map;

@Data
@Builder
public class DetectionTaskResultResponse {
    private String taskId;
    private String status;
    private String batchNo;
    private String workOrderNo;
    private String flowStatus;
    /** State hints only; each mutation rechecks current account permissions. */
    private List<DetectionQualityAction> qualityActions;
    private String qualityStation;
    private String assignee;
    private Long assignmentRevision;
    private String assignmentRemark;
    private String assignedAt;
    private String dueAt;
    private DetectionCaptureInfo captureInfo;
    private Integer totalImages;
    private Integer successfulImages;
    private Integer failedImages;
    private Map<String, Object> statistics;
    private List<Map<String, Object>> defectEvidence;
    private Integer defectCount;
    private String primaryDefectType;
    private String maxDefectSeverity;
    private List<DetectionPreviewImage> previewImages;
    private String resultJsonUrl;
    private String sourceOssPrefix;
    private String resultOssPrefix;
    private String detectionStartedAt;
    private String detectionFinishedAt;
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
}
