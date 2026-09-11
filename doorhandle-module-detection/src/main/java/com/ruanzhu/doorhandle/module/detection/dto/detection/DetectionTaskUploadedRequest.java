package com.ruanzhu.doorhandle.module.detection.dto.detection;

import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotEmpty;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

@Data
public class DetectionTaskUploadedRequest {
    private Integer modelId;
    @DecimalMin(value = "0.0", message = "阈值不能小于 0")
    @DecimalMax(value = "1.0", message = "阈值不能大于 1")
    private BigDecimal threshold = BigDecimal.valueOf(0.5);
    @NotEmpty(message = "上传文件列表不能为空")
    private List<DetectionUploadedFileItem> uploadedFiles;
}
