package com.ruanzhu.doorhandle.module.detection.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

class QualityDigestStatisticsTest {
    @Test void snapshotCountsOneImageBatchesAndLegacyRowsButSkipsSingleTestsAcrossStatuses() {
        var source = new DriverManagerDataSource("jdbc:h2:mem:" + UUID.randomUUID()
                + ";MODE=MySQL;DATABASE_TO_UPPER=false;DB_CLOSE_DELAY=-1");
        var jdbc = new JdbcTemplate(source);
        jdbc.execute("""
                CREATE TABLE detection_task(task_type VARCHAR(32), status VARCHAR(32), total_images INT,
                    successful_images INT DEFAULT 0, failed_images INT DEFAULT 0, defect_count INT DEFAULT 0,
                    review_status VARCHAR(32) DEFAULT 'PENDING', created_at TIMESTAMP DEFAULT '2026-01-03 11:00:00')
                """);
        jdbc.update("""
                INSERT INTO detection_task(task_type,status,total_images) VALUES
                    ('SINGLE','COMPLETED',1), ('SINGLE','FAILED',1), ('OSS_FOLDER','COMPLETED',1),
                    ('BATCH_DIRECT','COMPLETED',1), (NULL,'COMPLETED',4)
                """);
        var service = new QualityDigestService(jdbc, null, new ObjectMapper(),
                new DataSourceTransactionManager(source), null, "UTC");
        var groups = (List<?>) service.snapshot(LocalDate.of(2026,1,3)).get("statusGroups");
        assertThat(groups).hasSize(1);
        var row = (Map<?,?>) groups.get(0);
        assertThat(row.get("status")).isEqualTo("COMPLETED");
        assertThat(((Number) row.get("taskCount")).longValue()).isEqualTo(3L);
        assertThat(((Number) row.get("imageCount")).longValue()).isEqualTo(6L);
        assertThat(((Number) row.get("pendingReviewCount")).longValue()).isEqualTo(3L);
    }
}
