package com.ruanzhu.doorhandle.module.detection.dto.detection;

import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;

public final class DetectionApplicationHistory {
    private DetectionApplicationHistory() {}

    @Data
    public static class Entry {
        private String id;
        private String workUnitId;
        private String applicantUserId;
        private String assigneeUserId;
        private int imageCount;
        private String status;
        private String sourceBatchId;
        private boolean sourceAvailable;
        private String batchId;
        private boolean taskAvailable;
        private String workOrderNo;
        private LocalDateTime createdAt;
        private LocalDateTime assignedAt;
        private LocalDateTime decisionAt;
        private String decisionAccount;
        private String decisionReason;
    }

    public record Page(List<Entry> records, long total, long page, long size) {}
}
