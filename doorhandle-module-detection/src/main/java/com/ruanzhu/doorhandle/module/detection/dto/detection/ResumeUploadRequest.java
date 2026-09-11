package com.ruanzhu.doorhandle.module.detection.dto.detection;

import jakarta.validation.constraints.NotEmpty;
import lombok.Data;

import java.util.List;

@Data
public class ResumeUploadRequest {
    @NotEmpty(message = "文件列表不能为空")
    private List<DetectionUploadFileRequest> files;
}
