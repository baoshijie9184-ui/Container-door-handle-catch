package com.ruanzhu.doorhandle.module.detection.dto.detection;

import lombok.Builder;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

@Data
@Builder
public class DetectionTaskTraceResponse {
    private String taskId;
    private String workflowUuid;
    private String batchNo;
    private String workOrderNo;
    private String flowStatus;
    private String qualityStation;
    private String assignee;
    private Long assignmentRevision;
    private String assignmentRemark;
    private String assignedAt;
    private String dueAt;
    private String status;
    private String captureDate;
    private String region;
    private String collector;
    private String deviceName;
    private String imageFolderName;
    private Integer modelId;
    private String modelVersion;
    private BigDecimal threshold;
    private Integer totalImages;
    private Integer successfulImages;
    private Integer failedImages;
    private String sourceOssPrefix;
    private String resultOssPrefix;
    private String resultJsonKey;
    private String resultJsonUrl;
    private List<DetectionTraceImage> originalImages;
    private List<DetectionTraceImage> previewImages;
    private Map<String, Object> statistics;
    private List<Map<String, Object>> defectEvidence;
    private Integer defectCount;
    private String primaryDefectType;
    private String maxDefectSeverity;
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
    private List<DetectionTraceEvent> timeline;
}
