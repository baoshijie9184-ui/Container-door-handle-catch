package com.ruanzhu.doorhandle.module.detection.dto.detection;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class DetectionUploadFileRequest {
    @NotBlank(message = "文件名不能为空")
    private String fileName;
    private String contentType;
    private String relativePath;
    private Long fileSize;
}
