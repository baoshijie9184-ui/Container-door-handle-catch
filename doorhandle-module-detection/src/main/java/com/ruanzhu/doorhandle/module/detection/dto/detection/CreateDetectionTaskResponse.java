package com.ruanzhu.doorhandle.module.detection.dto.detection;

import lombok.Builder;
import lombok.Data;

import java.util.List;

@Data
@Builder
@lombok.extern.jackson.Jacksonized
public class CreateDetectionTaskResponse {
    private String taskId;
    private String version;
    private String workflowUuid;
    private String status;
    private String batchNo;
    private String workOrderNo;
    private String flowStatus;
    private String uploadPrefix;
    private DetectionCaptureInfo captureInfo;
    private List<DetectionUploadUrlItem> uploadUrls;
}
