package com.ruanzhu.doorhandle.module.detection.dto.detection;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class DuplicateTicketResolveRequest {
    @NotBlank(message = "处理结论不能为空")
    private String resolution; // ACCEPT_LEFT / ACCEPT_RIGHT / REDETECT
    @Size(max=2000,message="对比说明不能超过2000个字符")
    private String comparisonResult;
    @NotNull(message = "版本不能为空")
    private Integer expectedVersion;
}
