package com.ruanzhu.doorhandle.module.app.service.agent.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.detection.config.properties.DetectionWorkerProperties;
import com.ruanzhu.doorhandle.module.detection.config.properties.KafkaTaskProperties;
import com.ruanzhu.doorhandle.module.app.dto.chat.AgentExecutionResult;
import com.ruanzhu.doorhandle.module.app.dto.chat.AgentGraphHealthResponse;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.app.service.AgentGraphRunMonitor;
import com.ruanzhu.doorhandle.module.app.service.ChatBusinessCatalogService;
import com.ruanzhu.doorhandle.module.app.service.ChatCapabilityService;
import com.ruanzhu.doorhandle.module.app.service.DeepSeekClient;
import com.ruanzhu.doorhandle.module.infra.service.OssStorageService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class OpsAgentServiceImplTest {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    @Mock
    private DetectionTaskMapper detectionTaskMapper;

    @Mock
    private OssStorageService ossStorageService;

    @Mock
    private DeepSeekClient deepSeekClient;

    @Mock
    private AgentGraphRunMonitor agentGraphRunMonitor;

    @AfterEach
    void clearAuthentication() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void answerIncludesForeignFailedTaskForOperator() {
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(
                        "alice",
                        "N/A",
                        List.of(new SimpleGrantedAuthority("ROLE_OPERATOR"))));
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_20260611_151200_abcd1234");
        task.setCreatedBy("bob");
        task.setStatus("FAILED");
        when(detectionTaskMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(task);

        OpsAgentServiceImpl service = new OpsAgentServiceImpl(
                detectionTaskMapper,
                ossStorageService,
                new KafkaTaskProperties(),
                new DetectionWorkerProperties(),
                new ChatCapabilityService(),
                new ChatBusinessCatalogService(OBJECT_MAPPER),
                deepSeekClient,
                agentGraphRunMonitor,
                OBJECT_MAPPER,
                new DetectionTaskAccessPolicy()
        );

        assertNotNull(service.answer("检查检测链路", "alice"));
    }

    @Test
    void answerReportsKafkaAndRemoteWorkerStatus() {
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(
                        "alice", "N/A", List.of(new SimpleGrantedAuthority("ROLE_OPERATOR"))));
        KafkaTaskProperties kafkaTaskProperties = new KafkaTaskProperties();
        kafkaTaskProperties.setEnabled(true);
        kafkaTaskProperties.setBootstrapServers("kafka.remote.internal:9092");

        DetectionWorkerProperties workerProperties = new DetectionWorkerProperties();
        workerProperties.setEnabled(true);
        workerProperties.setDeployment("remote");
        workerProperties.setLabel("fastapi-worker-prod");

        when(ossStorageService.isConfigured()).thenReturn(true);
        when(detectionTaskMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);
        when(deepSeekClient.generateOpsResponse(anyString(), anyString()))
                .thenThrow(new RuntimeException("DeepSeek unavailable"));

        OpsAgentServiceImpl service = new OpsAgentServiceImpl(
                detectionTaskMapper,
                ossStorageService,
                kafkaTaskProperties,
                workerProperties,
                new ChatCapabilityService(),
                new ChatBusinessCatalogService(OBJECT_MAPPER),
                deepSeekClient,
                agentGraphRunMonitor,
                OBJECT_MAPPER,
                new DetectionTaskAccessPolicy()
        );

        AgentExecutionResult result = service.answer("检查检测链路", "tester");

        String content = result.getContent();
        assertTrue(content.contains("OSS"));
        assertTrue(content.contains("已配置"));
        assertTrue(content.contains("Kafka"));
        assertTrue(content.contains("已启用"));
        assertTrue(content.contains("远程检测"));
        assertTrue(content.contains("fastapi-worker-prod"));
    }

    @Test
    void answerListsBusinessCapabilitiesWhenAskedCoverage() {
        OpsAgentServiceImpl service = new OpsAgentServiceImpl(
                detectionTaskMapper,
                ossStorageService,
                new KafkaTaskProperties(),
                new DetectionWorkerProperties(),
                new ChatCapabilityService(),
                new ChatBusinessCatalogService(OBJECT_MAPPER),
                deepSeekClient,
                agentGraphRunMonitor,
                OBJECT_MAPPER,
                new DetectionTaskAccessPolicy()
        );

        AgentExecutionResult result = service.answer("智能助手能覆盖所有系统业务功能吗", "tester");

        String content = result.getContent();
        assertTrue(content.contains("检测任务与工业质检闭环"));
        assertTrue(content.contains("缺陷证据库"));
        assertTrue(content.contains("批次追溯报告"));
        assertTrue(content.contains("工单追溯报告"));
        assertTrue(content.contains("设备、人员和模型资源管理"));
        assertTrue(content.contains("报表与数据分析"));
        assertTrue(content.contains("系统运维与平台状态"));
        assertTrue(content.contains("Agent checkpoint"));
        assertTrue(content.contains("循环守卫"));
        assertTrue(content.contains("高风险写操作"));
    }

    @Test
    void answerListsBusinessEntryWhenAskedWhereFeatureIs() {
        OpsAgentServiceImpl service = new OpsAgentServiceImpl(
                detectionTaskMapper,
                ossStorageService,
                new KafkaTaskProperties(),
                new DetectionWorkerProperties(),
                new ChatCapabilityService(),
                new ChatBusinessCatalogService(OBJECT_MAPPER),
                deepSeekClient,
                agentGraphRunMonitor,
                OBJECT_MAPPER,
                new DetectionTaskAccessPolicy()
        );

        AgentExecutionResult result = service.answer("模型管理功能在哪个页面", "tester");

        assertTrue(result.getMessageType().contains("BUSINESS_CARD"));
        String content = result.getContent();
        assertTrue(content.contains("模型管理与 MLOps"));
        assertTrue(content.contains("#/models"));
        assertTrue(content.contains("\"agent\":\"RESOURCE\""));
        assertTrue(content.contains("查看模型评估指标"));
    }

    @Test
    void answerListsDefectGalleryEntryWhenAskedWhereFeatureIs() {
        OpsAgentServiceImpl service = new OpsAgentServiceImpl(
                detectionTaskMapper,
                ossStorageService,
                new KafkaTaskProperties(),
                new DetectionWorkerProperties(),
                new ChatCapabilityService(),
                new ChatBusinessCatalogService(OBJECT_MAPPER),
                deepSeekClient,
                agentGraphRunMonitor,
                OBJECT_MAPPER,
                new DetectionTaskAccessPolicy()
        );

        AgentExecutionResult result = service.answer("缺陷证据库在哪个页面", "tester");

        assertTrue(result.getMessageType().contains("BUSINESS_CARD"));
        String content = result.getContent();
        assertTrue(content.contains("缺陷证据库"));
        assertTrue(content.contains("#/detection?tab=defect-gallery"));
        assertTrue(content.contains("\"agent\":\"DETECTION\""));
        assertTrue(content.contains("查看严重缺陷证据"));
    }

    @Test
    void answerListsAgentDiagnosticsEntryWhenAskedWhereFeatureIs() {
        OpsAgentServiceImpl service = new OpsAgentServiceImpl(
                detectionTaskMapper,
                ossStorageService,
                new KafkaTaskProperties(),
                new DetectionWorkerProperties(),
                new ChatCapabilityService(),
                new ChatBusinessCatalogService(OBJECT_MAPPER),
                deepSeekClient,
                agentGraphRunMonitor,
                OBJECT_MAPPER,
                new DetectionTaskAccessPolicy()
        );

        AgentExecutionResult result = service.answer("Agent健康诊断在哪个页面", "tester");

        assertTrue(result.getMessageType().contains("BUSINESS_CARD"));
        String content = result.getContent();
        assertTrue(content.contains("Agent 可观测与稳定性"));
        assertTrue(content.contains("聊天面板右上角诊断按钮"));
        assertTrue(content.contains("\"agent\":\"OPS\""));
        assertTrue(content.contains("查看 Agent checkpoint 和健康状态"));
    }

    @Test
    void answerReturnsAgentHealthBusinessCard() throws Exception {
        AgentGraphHealthResponse health = new AgentGraphHealthResponse();
        health.setTotalRuns(20);
        health.setCompletedRuns(17);
        health.setGuardBreakRuns(2);
        health.setFallbackRuns(1);
        health.setAverageElapsedMs(180);
        health.setGuardBreakRate(0.1);
        health.setFallbackRate(0.05);
        health.setHealthStatus("WARN");
        health.setHealthMessage("智能体运行存在少量异常，建议关注 checkpoint 轨迹和最近守卫原因");
        health.setLastExitReason("GUARD_BREAK");
        health.setLastGuardReason("路由重复跳转次数过多");
        health.setLastUpdatedAt("2026-06-11 22:30:00");
        when(agentGraphRunMonitor.snapshot()).thenReturn(health);

        OpsAgentServiceImpl service = new OpsAgentServiceImpl(
                detectionTaskMapper,
                ossStorageService,
                new KafkaTaskProperties(),
                new DetectionWorkerProperties(),
                new ChatCapabilityService(),
                new ChatBusinessCatalogService(OBJECT_MAPPER),
                deepSeekClient,
                agentGraphRunMonitor,
                OBJECT_MAPPER,
                new DetectionTaskAccessPolicy()
        );

        AgentExecutionResult result = service.answer("查看 Agent checkpoint 和健康状态", "tester");

        assertTrue(result.getMessageType().contains("BUSINESS_CARD"));
        JsonNode payload = OBJECT_MAPPER.readTree(result.getContent());
        assertTrue(payload.path("type").asText().contains("agent-health"));
        assertTrue(payload.path("status").asText().contains("WARN"));
        assertTrue(payload.path("metrics").get(0).path("label").asText().contains("总运行"));
        assertTrue(payload.path("health").path("lastGuardReason").asText().contains("路由重复"));
    }
}
