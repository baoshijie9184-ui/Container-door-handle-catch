package com.ruanzhu.doorhandle.module.detection.dto.detection;

import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.Valid;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

@Data
public class CreateDetectionTaskRequest {
    private String taskType = "BATCH";
    @NotEmpty(message = "文件列表不能为空")
    @Valid
    private List<DetectionUploadFileRequest> files;
    @NotNull(message = "采集信息不能为空")
    @Valid
    private DetectionCaptureInfo captureInfo;
    private Integer modelId;
    @DecimalMin(value = "0.0", message = "阈值不能小于 0")
    @DecimalMax(value = "1.0", message = "阈值不能大于 1")
    private BigDecimal threshold = BigDecimal.valueOf(0.5);
    /** 聊天会话ID，从智能助手创建时传入，用于检测完成后通知 */
    private String sessionId;
}
