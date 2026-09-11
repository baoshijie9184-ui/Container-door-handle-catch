package com.ruanzhu.doorhandle.module.detection.dto.detection;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.util.List;

@Data
public class DetectionBatchPrecheckRequest {
    @NotEmpty(message = "图片列表不能为空")
    @Size(max = 5000, message = "单个工作单元最多 5000 张图片")
    @Valid
    private List<DetectionUploadedFileItem> files;

    /** UNDETECTED_ONLY 仅未成功检测；ALL 全部重新检测。 */
    private String strategy = "UNDETECTED_ONLY";
}
