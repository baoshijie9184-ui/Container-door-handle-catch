package com.ruanzhu.doorhandle.module.detection.dto.detection;

import lombok.Builder;
import lombok.Data;

import java.util.List;

@Data
@Builder
public class CreateDetectionTaskResponse {
    private String taskId;
    private String workflowUuid;
    private String status;
    private String batchNo;
    private String workOrderNo;
    private String flowStatus;
    private String uploadPrefix;
    private DetectionCaptureInfo captureInfo;
    private List<DetectionUploadUrlItem> uploadUrls;
}
