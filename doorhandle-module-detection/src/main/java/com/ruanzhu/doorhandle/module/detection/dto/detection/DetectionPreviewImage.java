package com.ruanzhu.doorhandle.module.detection.dto.detection;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class DetectionPreviewImage {
    private String imageName;
    private String originalUrl;
    private String annotatedUrl;
}
