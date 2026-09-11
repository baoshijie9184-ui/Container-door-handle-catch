package com.ruanzhu.doorhandle.module.detection.dto.detection;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class DetectionCaptureInfo {
    @NotBlank(message = "采集日期不能为空")
    private String captureDate;

    @NotBlank(message = "地区不能为空")
    private String region;

    @NotBlank(message = "采集员不能为空")
    private String collector;

    @NotBlank(message = "采集设备不能为空")
    private String deviceName;

    @NotBlank(message = "图片文件夹名称不能为空")
    private String imageFolderName;
}
