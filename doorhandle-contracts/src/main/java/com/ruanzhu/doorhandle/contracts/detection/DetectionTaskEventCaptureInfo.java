package com.ruanzhu.doorhandle.contracts.detection;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class DetectionTaskEventCaptureInfo {
    private String captureDate;
    private String region;
    private String collector;
    private String deviceName;
    private String imageFolderName;
}
