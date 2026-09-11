package com.ruanzhu.doorhandle.module.detection.dto.detection;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.Data;

@Data
public class DetectionWorkUnitApplyRequest {
    @Min(value = 1, message = "申请图片数量必须大于 0")
    @Max(value = 5000, message = "单个工作单元最多 5000 张图片")
    private Integer imageCount;
    private String strategy = "UNDETECTED_ONLY";
    private String modelVersion;
    private String remark;
}
