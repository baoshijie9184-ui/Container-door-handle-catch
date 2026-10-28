package com.ruanzhu.doorhandle.module.detection.dto.dashboard;

import io.swagger.v3.oas.annotations.media.Schema;
import java.time.LocalDateTime;
import java.util.List;

@Schema(description = "历史登记检测汇总，不要求关联原图或生成新版任务")
public record HistoricalDetectionSummary(
        long recordCount, long imageCount, Long targetCount, long modelCount,
        LocalDateTime firstRecordedAt, LocalDateTime lastRecordedAt,
        List<YearTotal> yearlyTotals) {
    public record YearTotal(int year, long recordCount, long imageCount, Long targetCount) { }
}
