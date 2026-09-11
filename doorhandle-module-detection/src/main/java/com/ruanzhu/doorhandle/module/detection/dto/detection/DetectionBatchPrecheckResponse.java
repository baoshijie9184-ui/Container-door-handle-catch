package com.ruanzhu.doorhandle.module.detection.dto.detection;

import lombok.Builder;
import lombok.Value;

import java.util.List;

@Value
@Builder
public class DetectionBatchPrecheckResponse {
    String precheckToken;
    String strategy;
    int total;
    int newCount;
    int detectedCount;
    int runningCount;
    int failedCount;
    List<Item> items;

    @Value
    @Builder
    public static class Item {
        String fileName;
        String objectKey;
        String sha256;
        String status;
        String lastTaskId;
    }
}
