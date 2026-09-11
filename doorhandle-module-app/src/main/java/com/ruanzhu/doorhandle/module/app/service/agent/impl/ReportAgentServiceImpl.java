package com.ruanzhu.doorhandle.module.app.service.agent.impl;

import com.ruanzhu.doorhandle.module.app.dto.chat.AgentExecutionResult;
import com.ruanzhu.doorhandle.module.detection.service.DashboardService;
import com.ruanzhu.doorhandle.module.app.service.DeepSeekClient;
import com.ruanzhu.doorhandle.module.app.service.agent.ReportAgentService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.Map;
import java.util.function.Consumer;

@Slf4j
@Service
@RequiredArgsConstructor
public class ReportAgentServiceImpl implements ReportAgentService {

    private final DashboardService dashboardService;
    private final DeepSeekClient deepSeekClient;

    @Override
    public String previewAction(String userPrompt) {
        return "这条请求会生成正式报表或摘要，属于需要确认的操作。确认后我会按当前数据给你生成一版文本简报。";
    }

    @Override
    public AgentExecutionResult answer(String userPrompt, String username) {
        return answer(userPrompt, username, null);
    }

    @Override
    public AgentExecutionResult answer(String userPrompt, String username, Consumer<String> tokenConsumer) {
        Map<String, Object> stats = dashboardService.getStats();
        String dataContext = buildStatsContext(stats);
        String content;
        try {
            content = tokenConsumer == null
                    ? deepSeekClient.generateReportResponse(userPrompt, dataContext)
                    : deepSeekClient.generateReportResponseStream(userPrompt, dataContext, tokenConsumer);
        } catch (Exception e) {
            log.warn("DeepSeek 回复生成失败，使用模板回复", e);
            content = "我先给你一版总览：检测记录总数 " + value(stats, "detectionCount")
                    + "，设备总数 " + value(stats, "deviceCount")
                    + "，人员总数 " + value(stats, "employeeCount")
                    + "，平均漏检率 " + value(stats, "avgMissRate") + "。";
        }
        return AgentExecutionResult.builder().messageType("TEXT").intent("REPORT_QUERY").content(content).build();
    }

    @Override
    public AgentExecutionResult executeConfirmedAction(String userPrompt, String username) {
        Map<String, Object> stats = dashboardService.getStats();
        String dataContext = buildStatsContext(stats);
        String content;
        try {
            content = deepSeekClient.generateReportResponse(userPrompt, dataContext);
        } catch (Exception e) {
            log.warn("DeepSeek 回复生成失败", e);
            content = "已为你生成简版报表摘要：当前检测记录 " + value(stats, "detectionCount")
                    + " 条，设备 " + value(stats, "deviceCount")
                    + " 台，人员 " + value(stats, "employeeCount")
                    + " 人，平均漏检率 " + value(stats, "avgMissRate")
                    + "。如果你要，我下一步可以继续扩展成按模型、设备、时间段的详细分析。";
        }
        return AgentExecutionResult.builder().messageType("TEXT").intent("REPORT_ACTION").content(content).build();
    }

    private String buildStatsContext(Map<String, Object> stats) {
        return "检测记录总数：" + value(stats, "detectionCount") + "\n"
                + "设备总数：" + value(stats, "deviceCount") + "\n"
                + "人员总数：" + value(stats, "employeeCount") + "\n"
                + "平均漏检率：" + value(stats, "avgMissRate") + "\n";
    }

    private Object value(Map<String, Object> stats, String key) {
        return stats == null ? "-" : stats.getOrDefault(key, "-");
    }
}
