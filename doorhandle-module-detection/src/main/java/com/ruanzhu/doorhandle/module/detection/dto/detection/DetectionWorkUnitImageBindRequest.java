package com.ruanzhu.doorhandle.module.detection.dto.detection;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotEmpty;
import lombok.Data;
import java.util.List;

@Data
public class DetectionWorkUnitImageBindRequest {
    @NotEmpty(message = "图片列表不能为空")
    @Valid
    private List<DetectionUploadedFileItem> images;
}
