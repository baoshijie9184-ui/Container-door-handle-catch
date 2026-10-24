package com.ruanzhu.doorhandle.module.detection.dto.detection;

/** State eligibility is separate from authorization; mutations always recheck both. */
public record DetectionQualityAction(
        String action,
        boolean stateAllowed,
        boolean supervisorRequired,
        String blockedReason
) {}
