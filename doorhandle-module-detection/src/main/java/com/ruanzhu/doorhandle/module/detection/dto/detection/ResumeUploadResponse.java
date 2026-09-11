package com.ruanzhu.doorhandle.module.detection.dto.detection;

import lombok.Builder;
import lombok.Data;

import java.util.List;

@Data
@Builder
public class ResumeUploadResponse {
    private String taskId;
    private List<DetectionUploadUrlItem> uploadUrls;
}
