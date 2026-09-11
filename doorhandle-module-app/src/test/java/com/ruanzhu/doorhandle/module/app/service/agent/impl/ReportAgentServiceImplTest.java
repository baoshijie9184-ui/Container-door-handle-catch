package com.ruanzhu.doorhandle.module.app.service.agent.impl;

import com.ruanzhu.doorhandle.module.app.dto.chat.AgentExecutionResult;
import com.ruanzhu.doorhandle.module.detection.service.DashboardService;
import com.ruanzhu.doorhandle.module.app.service.DeepSeekClient;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class ReportAgentServiceImplTest {

    private DashboardService dashboardService;
    private DeepSeekClient deepSeekClient;
    private ReportAgentServiceImpl reportAgentService;

    @BeforeEach
    void setUp() {
        dashboardService = mock(DashboardService.class);
        deepSeekClient = mock(DeepSeekClient.class);
        reportAgentService = new ReportAgentServiceImpl(dashboardService, deepSeekClient);
    }

    @Test
    void shouldRenderDashboardStatsUsingActualKeys() {
        Map<String, Object> stats = new HashMap<>();
        stats.put("detectionCount", 12);
        stats.put("deviceCount", 5);
        stats.put("employeeCount", 7);
        stats.put("avgMissRate", 1.25);
        when(dashboardService.getStats()).thenReturn(stats);
        when(deepSeekClient.generateReportResponse(anyString(), anyString()))
                .thenThrow(new RuntimeException("DeepSeek unavailable"));

        AgentExecutionResult result = reportAgentService.answer("给我看统计摘要", "admin");

        assertThat(result.getContent()).contains("12");
        assertThat(result.getContent()).contains("5");
        assertThat(result.getContent()).contains("7");
        assertThat(result.getContent()).contains("1.25");
        assertThat(result.getContent()).doesNotContain(" - ");
    }
}
