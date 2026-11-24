package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.detection.service.DashboardScope;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class StatisticsControllerTrendTest {
    private final StatisticsController controller = new StatisticsController();
    private final NamedParameterJdbcTemplate jdbc = mock(NamedParameterJdbcTemplate.class);

    @BeforeEach
    void authenticate() {
        ReflectionTestUtils.setField(controller, "scopedJdbc", jdbc);
        ReflectionTestUtils.setField(controller, "accessPolicy", new DetectionTaskAccessPolicy());
        SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken(
                "alice", null, List.of(new SimpleGrantedAuthority("ROLE_INSPECTOR"))));
    }

    @AfterEach
    void clearAuthentication() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void companyTrendPreservesIncompleteCoverageAndDistinguishesMissingFromZero() {
        when(jdbc.queryForList(anyString(), eq(Map.of()))).thenReturn(List.of(
                Map.of("date", "2026-04", "total", 25L, "taskCount", 1L, "classifiedTasks", 0L),
                Map.of("date", "2026-05", "total", 40L, "taskCount", 3L, "classifiedTasks", 2L,
                        "normal", 14L, "bent", 0L, "deformed", 3L, "rusty", 0L, "missing", 0L, "compromised", 0L)));

        var response = controller.getDetectionTrend("month", DashboardScope.COMPANY);
        assertEquals(200, response.getCode());
        var missing = response.getData().get(0);
        assertEquals("2026-04", missing.get("date"));
        assertEquals(25L, missing.get("total"));
        assertEquals(1L, missing.get("taskCount"));
        assertEquals(0L, missing.get("classifiedTasks"));
        assertNull(missing.get("normal"));
        var partial = response.getData().get(1);
        assertEquals(40L, partial.get("total"));
        assertEquals(3L, partial.get("taskCount"));
        assertEquals(2L, partial.get("classifiedTasks"));
        assertEquals(14L, partial.get("normal"));
        assertEquals(0L, partial.get("bent"));

        var sql = ArgumentCaptor.forClass(String.class);
        verify(jdbc).queryForList(sql.capture(), eq(Map.of()));
        assertTrue(sql.getValue().contains("detection_task.task_type <> 'SINGLE'"));
        assertTrue(sql.getValue().contains("a.source_batch_id=detection_task.task_id"));
        assertTrue(sql.getValue().contains("successful_images IS NULL OR successful_images <> 0"));
        assertTrue(sql.getValue().contains("COUNT(CASE WHEN classified THEN 1 END) AS classifiedTasks"));
        assertTrue(sql.getValue().contains("SUM(CASE WHEN classified THEN CAST(JSON_UNQUOTE(normal) AS DECIMAL(20,0)) END)"));
    }

    @Test
    void accountTrendPreservesLegacyDateAndMissingCountFallback() {
        var parameters = Map.of("scopeUsername", "alice");
        when(jdbc.queryForList(anyString(), eq(parameters))).thenReturn(List.of(
                Map.of("date", "2026-05", "total", 40L, "normal", 14L)));

        var response = controller.getDetectionTrend("month", DashboardScope.ACCOUNT);
        assertEquals(200, response.getCode());
        var row = response.getData().get(0);
        assertEquals("05月", row.get("date"));
        assertEquals(14L, row.get("normal"));
        assertEquals(0L, row.get("bent"));
        assertFalse(row.containsKey("taskCount"));
        assertFalse(row.containsKey("classifiedTasks"));

        var sql = ArgumentCaptor.forClass(String.class);
        verify(jdbc).queryForList(sql.capture(), eq(parameters));
        assertTrue(sql.getValue().contains("detection_task.created_by = :scopeUsername"));
        assertTrue(sql.getValue().contains("INTERVAL 12 MONTH"));
    }
}
