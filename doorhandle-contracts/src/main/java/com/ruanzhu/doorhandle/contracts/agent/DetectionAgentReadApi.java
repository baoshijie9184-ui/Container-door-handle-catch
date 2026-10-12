package com.ruanzhu.doorhandle.contracts.agent;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/** 检测模块向 Agent 提供的只读门面；不返回实体、OSS Key 或内部文件路径。 */
public interface DetectionAgentReadApi {
    record TaskView(String taskId, String status, String flowStatus, String deviceName,
                    Integer totalImages, Integer processedImages, Integer defectCount,
                    String reviewStatus, String reviewConclusion, LocalDateTime createdAt) {}
    record TaskPage(List<TaskView> items, long total, int page, int size) {}
    record Metrics(Map<String, Object> counts, LocalDateTime from, LocalDateTime to, String scope) {}

    TaskPage tasks(AgentActor actor, int page, int size, boolean qualityOnly);
    TaskView task(AgentActor actor, String taskId);
    Metrics metrics(AgentActor actor, int days);
}
