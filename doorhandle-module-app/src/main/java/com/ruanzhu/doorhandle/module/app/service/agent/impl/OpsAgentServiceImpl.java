package com.ruanzhu.doorhandle.module.app.service.agent.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.detection.config.properties.DetectionWorkerProperties;
import com.ruanzhu.doorhandle.module.detection.config.properties.KafkaTaskProperties;
import com.ruanzhu.doorhandle.module.app.dto.chat.AgentExecutionResult;
import com.ruanzhu.doorhandle.module.app.dto.chat.AgentGraphHealthResponse;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.app.service.AgentGraphRunMonitor;
import com.ruanzhu.doorhandle.module.app.service.ChatBusinessCatalogService;
import com.ruanzhu.doorhandle.module.app.service.ChatCapabilityService;
import com.ruanzhu.doorhandle.module.app.service.DeepSeekClient;
import com.ruanzhu.doorhandle.module.infra.service.OssStorageService;
import com.ruanzhu.doorhandle.module.app.service.agent.OpsAgentService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.util.StringUtils;

import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

@Slf4j
@Service
@RequiredArgsConstructor
public class OpsAgentServiceImpl implements OpsAgentService {

    private final DetectionTaskMapper detectionTaskMapper;
    private final OssStorageService ossStorageService;
    private final KafkaTaskProperties kafkaTaskProperties;
    private final DetectionWorkerProperties detectionWorkerProperties;
    private final ChatCapabilityService chatCapabilityService;
    private final ChatBusinessCatalogService chatBusinessCatalogService;
    private final DeepSeekClient deepSeekClient;
    private final AgentGraphRunMonitor agentGraphRunMonitor;
    private final ObjectMapper objectMapper;
    private final DetectionTaskAccessPolicy detectionTaskAccessPolicy;

    @Override
    public AgentExecutionResult answer(String userPrompt, String username) {
        return answer(userPrompt, username, null);
    }

    @Override
    public AgentExecutionResult answer(String userPrompt, String username, Consumer<String> tokenConsumer) {
        if (isModelIdentityQuestion(userPrompt)) {
            return AgentExecutionResult.builder()
                    .messageType("TEXT")
                    .intent("OPS_QUERY")
                    .content("我是当前系统配置的 Agent 智能助手，使用 DashScope 兼容接口上的 kimi-k3 大语言模型提供意图识别和对话服务。")
                    .build();
        }
        if (chatBusinessCatalogService.isBusinessMapQuestion(userPrompt)) {
            return AgentExecutionResult.builder()
                    .messageType("BUSINESS_CARD")
                    .intent("OPS_QUERY")
                    .content(chatBusinessCatalogService.buildBusinessMapCard(userPrompt))
                    .build();
        }
        if (isCapabilityQuestion(userPrompt)) {
            return AgentExecutionResult.builder()
                    .messageType("TEXT")
                    .intent("OPS_QUERY")
                    .content(chatCapabilityService.buildCapabilityOverview())
                    .build();
        }
        if (isAgentHealthQuestion(userPrompt)) {
            return AgentExecutionResult.builder()
                    .messageType("BUSINESS_CARD")
                    .intent("OPS_QUERY")
                    .content(buildAgentHealthCard(agentGraphRunMonitor.snapshot()))
                    .build();
        }

        LambdaQueryWrapper<DetectionTask> failedTaskQuery = new LambdaQueryWrapper<DetectionTask>()
                .eq(DetectionTask::getStatus, "FAILED")
                .orderByDesc(DetectionTask::getUpdatedAt)
                .last("limit 1");
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        detectionTaskAccessPolicy.assertAuthenticated(authentication);
        DetectionTask failedTask = detectionTaskMapper.selectOne(failedTaskQuery);
        if (failedTask != null) {
            detectionTaskAccessPolicy.assertCanAccess(failedTask, authentication);
        }

        StringBuilder data = new StringBuilder();
        data.append("OSS 配置状态：").append(ossStorageService.isConfigured() ? "已配置" : "未配置").append("\n");
        data.append("Kafka 状态：").append(kafkaTaskProperties.isEnabled() ? "已启用" : "未启用");
        if (StringUtils.hasText(kafkaTaskProperties.getBootstrapServers())) {
            data.append("，服务器：").append(kafkaTaskProperties.getBootstrapServers());
        }
        data.append("\n");
        data.append("远程检测 Worker：").append(detectionWorkerProperties.isEnabled() ? "已启用" : "未启用");
        if (StringUtils.hasText(detectionWorkerProperties.getLabel())) {
            data.append("，标签：").append(detectionWorkerProperties.getLabel());
        }
        data.append("\n");
        if (failedTask != null) {
            data.append("最近失败任务：").append(failedTask.getTaskId())
                    .append("，失败信息：").append(StringUtils.hasText(failedTask.getErrorMessage()) ? failedTask.getErrorMessage() : "未记录详细错误");
        } else {
            data.append("最近失败任务：无");
        }

        String content;
        try {
            content = tokenConsumer == null
                    ? deepSeekClient.generateOpsResponse(userPrompt, data.toString())
                    : deepSeekClient.generateOpsResponseStream(userPrompt, data.toString(), tokenConsumer);
        } catch (Exception e) {
            log.warn("DeepSeek 回复生成失败，使用模板回复", e);
            content = fallbackOpsAnswer(data.toString());
        }
        return AgentExecutionResult.builder().messageType("TEXT").intent("OPS_QUERY").content(content).build();
    }

    private String fallbackOpsAnswer(String data) {
        return "运维侧快速检查结果如下：\n" + data;
    }

    private boolean isCapabilityQuestion(String userPrompt) {
        String text = userPrompt == null ? "" : userPrompt.toLowerCase();
        return text.contains("能做什么")
                || text.contains("功能")
                || text.contains("覆盖")
                || text.contains("系统业务")
                || text.contains("所有业务")
                || text.contains("能力");
    }

    private boolean isModelIdentityQuestion(String userPrompt) {
        String text = userPrompt == null ? "" : userPrompt.toLowerCase();
        return text.contains("你是什么模型") || text.contains("你是什么大语言模型")
                || text.contains("你是哪个模型") || text.contains("大语言模型")
                || text.contains("什么llm") || text.contains("你是谁");
    }

    private boolean isAgentHealthQuestion(String userPrompt) {
        String text = userPrompt == null ? "" : userPrompt.toLowerCase();
        return text.contains("agent健康")
                || text.contains("agent 健康")
                || text.contains("checkpoint")
                || text.contains("check point")
                || text.contains("循环守卫")
                || text.contains("守卫中断")
                || text.contains("路由轨迹")
                || text.contains("智能体健康")
                || text.contains("智能体状态");
    }

    private String buildAgentHealthCard(AgentGraphHealthResponse health) {
        AgentGraphHealthResponse safeHealth = health == null ? new AgentGraphHealthResponse() : health;
        Map<String, Object> payload = Map.of(
                "type", "agent-health",
                "title", "Agent 健康状态",
                "description", safeText(safeHealth.getHealthMessage(), "已汇总智能体运行、checkpoint、循环守卫和兜底情况。"),
                "status", safeText(safeHealth.getHealthStatus(), "UNKNOWN"),
                "metrics", List.of(
                        Map.of("label", "总运行", "value", safeHealth.getTotalRuns(), "tone", "blue"),
                        Map.of("label", "完成", "value", safeHealth.getCompletedRuns(), "tone", "indigo"),
                        Map.of("label", "守卫中断", "value", safeHealth.getGuardBreakRuns(), "tone", "red"),
                        Map.of("label", "兜底", "value", safeHealth.getFallbackRuns(), "tone", "amber"),
                        Map.of("label", "平均耗时", "value", safeHealth.getAverageElapsedMs() + "ms", "tone", "orange"),
                        Map.of("label", "守卫率", "value", percentText(safeHealth.getGuardBreakRate()), "tone", "rose")
                ),
                "health", Map.of(
                        "fallbackRate", percentText(safeHealth.getFallbackRate()),
                        "lastExitReason", safeText(safeHealth.getLastExitReason(), "UNKNOWN"),
                        "lastGuardReason", safeText(safeHealth.getLastGuardReason(), "暂无"),
                        "lastUpdatedAt", safeText(safeHealth.getLastUpdatedAt(), "暂无")
                ),
                "actions", List.of(
                        "查看 Agent checkpoint 和健康状态",
                        "智能体为什么触发循环守卫",
                        "系统业务地图和功能入口"
                ),
                "note", "如果守卫中断率或兜底率持续升高，建议检查路由关键词、节点执行日志、外部模型可用性和最近 checkpoint。"
        );
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (JsonProcessingException e) {
            throw new BusinessException("Agent 健康卡片序列化失败");
        }
    }

    private String percentText(double value) {
        return String.format(java.util.Locale.ROOT, "%.1f%%", value * 100D);
    }

    private String safeText(String value, String fallback) {
        return StringUtils.hasText(value) ? value : fallback;
    }
}
