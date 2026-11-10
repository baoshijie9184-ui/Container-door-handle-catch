package com.ruanzhu.doorhandle.module.detection.dto.detection;

import lombok.Builder;
import lombok.Data;

import java.util.List;

@Data
@Builder
@lombok.extern.jackson.Jacksonized
public class ResumeUploadResponse {
    private String taskId;
    private String version;
    private List<DetectionUploadUrlItem> uploadUrls;
}
