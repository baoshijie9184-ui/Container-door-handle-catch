package com.ruanzhu.doorhandle.module.detection.service.detection;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import java.util.Set;

/** Shared by the business page and confirmed Agent commands. */
public final class DetectionRetryPolicy {
    private DetectionRetryPolicy() {}
    public static void assertEligible(DetectionTask task, ObjectMapper json) {
        if (Set.of("RELEASED","SCRAPPED","ARCHIVED").contains(value(task.getFlowStatus()))
                || !Set.of("FAILED","COMPLETED","PARTIAL_FAILED").contains(value(task.getStatus()))
                || !("FAILED".equals(task.getStatus()) || Set.of("FAILED","RECHECK_REQUIRED","REWORK_REQUIRED").contains(value(task.getFlowStatus()))))
            throw new BusinessException("当前任务状态不支持重新检测");
        try {
            var keys=json.readTree(task.getOriginalImageKeysJson());
            if (keys==null || !keys.isArray() || keys.isEmpty()) throw new IllegalArgumentException();
            for(var key:keys) if(!key.isTextual() || key.asText().isBlank()) throw new IllegalArgumentException();
        } catch(Exception error) { throw new BusinessException("任务缺少有效原图证据，无法重新检测"); }
    }
    private static String value(String value) { return value==null?"":value; }
}
