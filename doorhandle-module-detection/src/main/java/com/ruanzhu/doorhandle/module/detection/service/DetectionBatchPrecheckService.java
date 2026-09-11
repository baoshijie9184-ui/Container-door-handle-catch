package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionBatchPrecheckRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionBatchPrecheckResponse;

public interface DetectionBatchPrecheckService {
    DetectionBatchPrecheckResponse precheck(DetectionBatchPrecheckRequest request, String ownerUserId);
}
