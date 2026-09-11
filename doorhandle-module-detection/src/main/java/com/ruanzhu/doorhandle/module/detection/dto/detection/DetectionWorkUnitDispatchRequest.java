package com.ruanzhu.doorhandle.module.detection.dto.detection;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

@Data
public class DetectionWorkUnitDispatchRequest {
    @NotBlank(message = "被派发员工不能为空")
    private String assigneeUserId;
    @NotNull(message = "版本不能为空")
    private Integer expectedVersion;
    private String remark;
}
