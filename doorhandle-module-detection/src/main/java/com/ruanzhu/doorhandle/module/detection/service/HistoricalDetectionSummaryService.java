package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.module.detection.dto.dashboard.HistoricalDetectionSummary;
import com.ruanzhu.doorhandle.module.detection.dto.dashboard.HistoricalDetectionSummary.YearTotal;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDateTime;
import java.util.List;

@Service
public class HistoricalDetectionSummaryService {
    private final JdbcTemplate jdbc;
    private final DetectionTaskAccessPolicy accessPolicy;

    public HistoricalDetectionSummaryService(JdbcTemplate jdbc, DetectionTaskAccessPolicy accessPolicy) {
        this.jdbc = jdbc;
        this.accessPolicy = accessPolicy;
    }

    @Transactional(readOnly = true)
    public HistoricalDetectionSummary summary() {
        var authentication = SecurityContextHolder.getContext().getAuthentication();
        accessPolicy.assertAuthenticated(authentication);
        if (!accessPolicy.isAdmin(authentication)) throw new AccessDeniedException("历史累计仅限企业管理账号查看");
        // Legacy rows are aggregate records. Do not require image paths, rewrite totals,
        // or merge them into current task/approval/quality-workload counters.
        var total = jdbc.queryForObject("""
                SELECT COUNT(*) AS records, COALESCE(SUM(detected_images_count),0) AS images,
                       SUM(detection_instances_count) AS targets, COUNT(DISTINCT model_id) AS models,
                       MIN(start_time) AS first_recorded, MAX(COALESCE(finished_at,start_time)) AS last_recorded
                FROM image_detection_data
                """, (row, index) -> new HistoricalDetectionSummary(
                row.getLong("records"), row.getLong("images"), nullableLong(row, "targets"),
                row.getLong("models"), row.getObject("first_recorded", LocalDateTime.class),
                row.getObject("last_recorded", LocalDateTime.class), List.of()));
        var years = jdbc.query("""
                SELECT YEAR(start_time) AS recorded_year, COUNT(*) AS records,
                       COALESCE(SUM(detected_images_count),0) AS images,
                       SUM(detection_instances_count) AS targets
                FROM image_detection_data WHERE start_time IS NOT NULL
                GROUP BY YEAR(start_time) ORDER BY recorded_year
                """, (row, index) -> new YearTotal(row.getInt("recorded_year"), row.getLong("records"),
                row.getLong("images"), nullableLong(row, "targets")));
        return new HistoricalDetectionSummary(total.recordCount(), total.imageCount(), total.targetCount(),
                total.modelCount(), total.firstRecordedAt(), total.lastRecordedAt(), years);
    }

    private static Long nullableLong(ResultSet row, String name) throws SQLException {
        long value = row.getLong(name);
        return row.wasNull() ? null : value;
    }

}
