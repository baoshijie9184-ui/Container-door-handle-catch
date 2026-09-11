package com.ruanzhu.doorhandle.module.detection.dto.detection;

import jakarta.validation.constraints.Min;
import lombok.Data;

@Data
public class DetectionWorkUnitSubmitRequest {
    @Min(value = 0, message = "完成数量不能为负数")
    private Integer completedCount;
    private String remark;
    @jakarta.validation.constraints.NotNull(message = "版本不能为空")
    @Min(value = 0, message = "版本不能为负数")
    private Integer expectedVersion;
}
