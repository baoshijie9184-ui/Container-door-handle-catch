package com.ruanzhu.doorhandle.module.detection.dto.detection;

import lombok.Data;

@Data
public class DetectionReworkResultRequest {
    private String reworkResult;
    private String reworkOperator;
    private String reworkRemark;
    private Boolean recheckRequired;
}
