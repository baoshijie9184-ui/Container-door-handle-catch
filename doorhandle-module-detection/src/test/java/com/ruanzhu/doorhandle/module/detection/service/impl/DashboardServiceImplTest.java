package com.ruanzhu.doorhandle.module.detection.service.impl;

import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class DashboardServiceImplTest {

    @Test
    void getQualityDispositionStatsSummarizesPendingAndDispositionActions() {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        DashboardServiceImpl dashboardService = new DashboardServiceImpl();
        ReflectionTestUtils.setField(dashboardService, "jdbcTemplate", jdbcTemplate);

        when(jdbcTemplate.queryForList(org.mockito.ArgumentMatchers.contains("summary")))
                .thenReturn(List.of(Map.of(
                        "reviewedCount", 8,
                        "pendingDispositionCount", 3,
                        "disposedCount", 5,
                        "recheckRequiredCount", 2
                )));
        when(jdbcTemplate.queryForList(org.mockito.ArgumentMatchers.contains("disposition_action")))
                .thenReturn(List.of(
                        Map.of("action", "REWORK", "count", 2),
                        Map.of("action", "RELEASE", "count", 3)
                ));

        Map<String, Object> stats = dashboardService.getQualityDispositionStats();

        assertEquals(8, stats.get("reviewedCount"));
        assertEquals(3, stats.get("pendingDispositionCount"));
        assertEquals(5, stats.get("disposedCount"));
        assertEquals(2, stats.get("recheckRequiredCount"));

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> series = (List<Map<String, Object>>) stats.get("series");
        assertEquals(5, series.size());
        assertTrue(series.contains(Map.of("name", "返工", "value", 2)));
        assertTrue(series.contains(Map.of("name", "放行", "value", 3)));
        assertTrue(series.contains(Map.of("name", "复检", "value", 0)));
        assertTrue(series.contains(Map.of("name", "隔离", "value", 0)));
        assertTrue(series.contains(Map.of("name", "报废", "value", 0)));
    }

    @Test
    void getQualityWorkloadSummarizesActionableInspectionQueues() {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        DashboardServiceImpl dashboardService = new DashboardServiceImpl();
        ReflectionTestUtils.setField(dashboardService, "jdbcTemplate", jdbcTemplate);

        when(jdbcTemplate.queryForList(org.mockito.ArgumentMatchers.contains("pendingReviewCount")))
                .thenReturn(List.of(Map.of(
                        "pendingReviewCount", 4,
                        "pendingDispositionCount", 3,
                        "recheckRequiredCount", 2,
                        "reworkRequiredCount", 5,
                        "holdCount", 1,
                        "failedCount", 6
                )));

        Map<String, Object> workload = dashboardService.getQualityWorkload();

        assertEquals(4, workload.get("pendingReviewCount"));
        assertEquals(3, workload.get("pendingDispositionCount"));
        assertEquals(2, workload.get("recheckRequiredCount"));
        assertEquals(5, workload.get("reworkRequiredCount"));
        assertEquals(1, workload.get("holdCount"));
        assertEquals(6, workload.get("failedCount"));
        assertEquals(21, workload.get("totalActionableCount"));

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> queues = (List<Map<String, Object>>) workload.get("queues");
        assertEquals(6, queues.size());
        assertEquals(Map.of("name", "待复核", "status", "PENDING_REVIEW", "count", 4), queues.get(0));
        assertEquals(Map.of("name", "待处置", "status", "PENDING_DISPOSITION", "count", 3), queues.get(1));
    }
}
