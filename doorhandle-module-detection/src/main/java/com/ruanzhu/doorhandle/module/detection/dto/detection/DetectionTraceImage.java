package com.ruanzhu.doorhandle.module.detection.dto.detection;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class DetectionTraceImage {
    private String imageName;
    private String objectKey;
    private String previewUrl;
}
