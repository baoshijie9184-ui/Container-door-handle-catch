package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionApplicationHistory;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitApplyRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitDecisionRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitSubmitRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitDispatchRequest;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionWorkUnit;
import java.util.List;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitImageBindRequest;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionWorkUnitImage;

public interface DetectionWorkUnitService {
    DetectionWorkUnit apply(DetectionWorkUnitApplyRequest request);
    DetectionWorkUnit reject(String workUnitId, DetectionWorkUnitDecisionRequest request);
    DetectionWorkUnit withdraw(String workUnitId, DetectionWorkUnitDecisionRequest request);
    List<DetectionWorkUnit> listMine(String userId);
    List<DetectionWorkUnit> listActive();
    DetectionApplicationHistory.Page applicationHistory(int page, int size, String keyword, String taskId);
    DetectionWorkUnit submit(String workUnitId, DetectionWorkUnitSubmitRequest request, String userId);
    DetectionWorkUnit dispatch(String workUnitId, DetectionWorkUnitDispatchRequest request, String operator);
    DetectionWorkUnit recall(String workUnitId, Integer expectedVersion, String operator);
    List<DetectionWorkUnitImage> bindImages(String workUnitId, DetectionWorkUnitImageBindRequest request, String operator);
    List<DetectionWorkUnitImage> listImages(String workUnitId);
}
