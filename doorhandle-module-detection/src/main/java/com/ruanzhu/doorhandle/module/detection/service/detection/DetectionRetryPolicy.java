package com.ruanzhu.doorhandle.module.detection.service.detection;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import java.util.Set;

/** Shared by the business page and confirmed Agent commands. */
public final class DetectionRetryPolicy {
    private static final String MISSING_ORIGINAL_IMAGES = "任务缺少有效原图清单，无法重新检测";

    private DetectionRetryPolicy() {}
    public static void assertEligible(DetectionTask task, ObjectMapper json) {
        if (Set.of("RELEASED","SCRAPPED","ARCHIVED").contains(value(task.getFlowStatus()))
                || !Set.of("FAILED","COMPLETED","PARTIAL_FAILED").contains(value(task.getStatus()))
                || "REWORK_REQUIRED".equals(task.getFlowStatus())
                || !("FAILED".equals(task.getStatus()) || Set.of("FAILED","RECHECK_REQUIRED").contains(value(task.getFlowStatus()))))
            throw new BusinessException("当前任务状态不支持重新检测");
        String evidence = originalImageEvidenceReason(task.getOriginalImageKeysJson(),json);
        if (evidence != null) throw new BusinessException(evidence);
    }

    public static String originalImageEvidenceReason(String originalKeys, ObjectMapper json) {
        if (originalKeys == null || originalKeys.isBlank()) return MISSING_ORIGINAL_IMAGES;
        try {
            var keys = json.readTree(originalKeys);
            if (keys == null || !keys.isArray() || keys.isEmpty()) return MISSING_ORIGINAL_IMAGES;
            for (var key : keys) {
                if (!key.isTextual() || key.asText().isBlank()) return MISSING_ORIGINAL_IMAGES;
            }
            return null;
        } catch (com.fasterxml.jackson.core.JsonProcessingException error) {
            return MISSING_ORIGINAL_IMAGES;
        }
    }

    private static String value(String value) { return value==null?"":value; }
}
