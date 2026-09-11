package com.ruanzhu.doorhandle.module.detection.dto.detection;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

@Data
public class DuplicateTicketResolveRequest {
    @NotBlank(message = "处理结论不能为空")
    private String resolution; // ACCEPT_LEFT / ACCEPT_RIGHT / REDetect
    private String comparisonResult;
    @NotNull(message = "版本不能为空")
    private Integer expectedVersion;
}
