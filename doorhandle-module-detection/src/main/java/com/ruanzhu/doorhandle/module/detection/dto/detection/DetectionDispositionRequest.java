package com.ruanzhu.doorhandle.module.detection.dto.detection;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class DetectionDispositionRequest {

    @NotBlank(message = "处置动作不能为空")
    @Pattern(regexp = "^(RELEASE|REWORK|RECHECK|HOLD|SCRAP)$",
            message = "处置动作必须是 RELEASE、REWORK、RECHECK、HOLD 或 SCRAP")
    private String dispositionAction;

    private Boolean recheckRequired;

    @Size(max = 1000, message = "处置备注不能超过 1000 个字符")
    private String dispositionRemark;
}
