package com.ruanzhu.doorhandle.module.device.dto.device;

import lombok.Data;

import java.util.Map;

@Data
public class DeviceHeartbeatRequest {
    private String stationCode;
    private String edgeNodeId;
    private String plcStatus;
    private String cameraStatus;
    private String captureStatus;
    private String lastImageKey;
    private String lastCaptureAt;
    private Map<String, Object> runtimeMetadata;
    private String alertLevel;
    private String alertMessage;
}
