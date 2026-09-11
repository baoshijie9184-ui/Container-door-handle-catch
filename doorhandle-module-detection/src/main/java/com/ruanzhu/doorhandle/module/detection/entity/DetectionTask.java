package com.ruanzhu.doorhandle.module.detection.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
@TableName("detection_task")
public class DetectionTask {

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    @TableField("task_id")
    private String taskId;

    @TableField("workflow_uuid")
    private String workflowUuid;

    @TableField("task_type")
    private String taskType;

    @TableField("batch_no")
    private String batchNo;

    @TableField("work_order_no")
    private String workOrderNo;

    @TableField("flow_status")
    private String flowStatus;

    @TableField("quality_station")
    private String qualityStation;

    @TableField("assignee")
    private String assignee;

    @TableField("assignment_remark")
    private String assignmentRemark;

    @TableField("assigned_at")
    private LocalDateTime assignedAt;

    @TableField("due_at")
    private LocalDateTime dueAt;

    @TableField("status")
    private String status;

    @TableField("stage")
    private String stage;

    @TableField("dispatch_id")
    private String dispatchId;

    @TableField("last_finished_event_id")
    private String lastFinishedEventId;

    @TableField("model_id")
    private Integer modelId;

    @TableField("model_version")
    private String modelVersion;

    @TableField("threshold")
    private BigDecimal threshold;

    @TableField("capture_date")
    private String captureDate;

    @TableField("region")
    private String region;

    @TableField("collector")
    private String collector;

    @TableField("device_name")
    private String deviceName;

    @TableField("image_folder_name")
    private String imageFolderName;

    @TableField("total_images")
    private Integer totalImages;

    @TableField("processed_images")
    private Integer processedImages;

    @TableField("successful_images")
    private Integer successfulImages;

    @TableField("failed_images")
    private Integer failedImages;

    @TableField("source_oss_prefix")
    private String sourceOssPrefix;

    @TableField("result_oss_prefix")
    private String resultOssPrefix;

    @TableField("result_json_oss_key")
    private String resultJsonOssKey;

    @TableField("original_image_keys_json")
    private String originalImageKeysJson;

    @TableField("preview_image_keys_json")
    private String previewImageKeysJson;

    @TableField("statistics_json")
    private String statisticsJson;

    @TableField("defect_evidence_json")
    private String defectEvidenceJson;

    @TableField("defect_count")
    private Integer defectCount;

    @TableField("primary_defect_type")
    private String primaryDefectType;

    @TableField("max_defect_severity")
    private String maxDefectSeverity;

    @TableField("error_message")
    private String errorMessage;

    @TableField("review_status")
    private String reviewStatus;

    @TableField("review_conclusion")
    private String reviewConclusion;

    @TableField("severity_level")
    private String severityLevel;

    @TableField("confirmed_defect_count")
    private Integer confirmedDefectCount;

    @TableField("false_positive_count")
    private Integer falsePositiveCount;

    @TableField("review_remark")
    private String reviewRemark;

    @TableField("reviewer")
    private String reviewer;

    @TableField("reviewed_at")
    private LocalDateTime reviewedAt;

    @TableField("disposition_status")
    private String dispositionStatus;

    @TableField("disposition_action")
    private String dispositionAction;

    @TableField("disposition_remark")
    private String dispositionRemark;

    @TableField("disposition_operator")
    private String dispositionOperator;

    @TableField("disposed_at")
    private LocalDateTime disposedAt;

    @TableField("recheck_required")
    private Boolean recheckRequired;

    @TableField("rework_result")
    private String reworkResult;

    @TableField("rework_operator")
    private String reworkOperator;

    @TableField("rework_remark")
    private String reworkRemark;

    @TableField("rework_completed_at")
    private LocalDateTime reworkCompletedAt;

    @TableField("session_id")
    private String sessionId;

    @TableField("created_by")
    private String createdBy;

    @TableField("created_at")
    private LocalDateTime createdAt;

    @TableField("started_at")
    private LocalDateTime startedAt;

    @TableField("finished_at")
    private LocalDateTime finishedAt;

    @TableField("updated_at")
    private LocalDateTime updatedAt;
}
