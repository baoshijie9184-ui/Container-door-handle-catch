package com.ruanzhu.doorhandle.module.detection.dto.detection;

import com.fasterxml.jackson.databind.JsonNode;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.util.List;

public final class HistoricalDetectionLedger {
    private HistoricalDetectionLedger() {}

    public record Entry(String id, Integer modelId, String modelName, Integer detectedImages,
                        LocalDateTime startTime, LocalDateTime finishedAt,
                        String supervisorUsername, String supervisorName, String inspectorEmployeeNumber,
                        String inspectorName, String inspectorUsername, OffsetDateTime assignedAt) {}

    public record Page(List<Entry> records, long total, int page, int size) {}

    public record Assignment(JsonNode id, String supervisorUsername, String inspectorEmployeeNumber) {}

    public record Assignments(List<Assignment> assignments) {}

    public record Assigned(int assigned, int unchanged, int total) {}
}
