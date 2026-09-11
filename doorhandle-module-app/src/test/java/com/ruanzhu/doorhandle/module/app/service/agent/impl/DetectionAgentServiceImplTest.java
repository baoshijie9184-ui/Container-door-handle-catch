package com.ruanzhu.doorhandle.module.app.service.agent.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import com.ruanzhu.doorhandle.module.app.dto.chat.AgentExecutionResult;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionDispositionRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskProgressResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadFileRequest;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.app.service.ChatSessionService;
import com.ruanzhu.doorhandle.module.app.service.DeepSeekClient;
import com.ruanzhu.doorhandle.module.detection.service.DetectionTaskDispatchService;
import com.ruanzhu.doorhandle.module.detection.service.DetectionTaskService;
import com.ruanzhu.doorhandle.module.app.service.DetectionUploadAsyncService;
import com.ruanzhu.doorhandle.module.infra.service.OssStorageService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.never;

@ExtendWith(MockitoExtension.class)
class DetectionAgentServiceImplTest {

    @Mock
    private DetectionTaskMapper detectionTaskMapper;

    @Mock
    private DeepSeekClient deepSeekClient;

    @Mock
    private DetectionTaskService detectionTaskService;

    @Mock
    private ChatSessionService chatSessionService;

    @Mock
    private OssStorageService ossStorageService;

    @Mock
    private DetectionUploadAsyncService uploadAsyncService;

    @Mock
    private DetectionTaskDispatchService detectionTaskDispatchService;

    @TempDir
    private Path tempDir;

    @BeforeEach
    void authenticateAsAdmin() {
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(
                        "admin",
                        "N/A",
                        List.of(new SimpleGrantedAuthority("ROLE_ADMIN"))));
    }

    @AfterEach
    void clearAuthentication() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void scanImageFilesKeepsRelativePathForNestedFolders() throws Exception {
        Files.createDirectories(tempDir.resolve("camera-a"));
        Files.createDirectories(tempDir.resolve("camera-b"));
        Files.writeString(tempDir.resolve("camera-a").resolve("img001.jpg"), "camera-a");
        Files.writeString(tempDir.resolve("camera-b").resolve("img001.jpg"), "camera-b");

        DetectionAgentServiceImpl service = newService();

        @SuppressWarnings("unchecked")
        List<DetectionUploadFileRequest> files = (List<DetectionUploadFileRequest>)
                ReflectionTestUtils.invokeMethod(service, "scanImageFiles", tempDir);

        assertThat(files).extracting(DetectionUploadFileRequest::getRelativePath)
                .contains("camera-a/img001.jpg", "camera-b/img001.jpg");
    }

    @Test
    void validateAgentScanPathRejectsPathOutsideAllowedRoots() {
        ChatAssistantProperties properties = new ChatAssistantProperties();
        properties.setAllowedScanRoots(List.of(tempDir.resolve("uploads").toString()));
        DetectionAgentServiceImpl service = newService(properties);

        assertThatThrownBy(() -> ReflectionTestUtils.invokeMethod(
                service,
                "validateAgentScanPath",
                tempDir.resolve(".ssh")
        )).hasMessageContaining("敏感目录");
    }

    @Test
    void answerReturnsQualityQueueBusinessCard() throws Exception {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_20260611_151200_abcd1234");
        task.setWorkOrderNo("WO-001");
        task.setBatchNo("BATCH-001");
        task.setStatus("COMPLETED");
        task.setFlowStatus("REWORK_REQUIRED");
        task.setReviewStatus("PENDING");
        task.setDispositionStatus("PENDING");
        task.setAssignee("张三");
        task.setDefectCount(3);
        task.setMaxDefectSeverity("HIGH");
        task.setPrimaryDefectType("划痕");

        when(detectionTaskMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(task));

        DetectionAgentServiceImpl service = newService();

        AgentExecutionResult result = service.answer("查看待复核质检队列和返工复检任务", "tester");

        assertThat(result.getMessageType()).isEqualTo("BUSINESS_CARD");
        assertThat(result.getIntent()).isEqualTo("DETECTION_QUERY");
        JsonNode payload = new ObjectMapper().readTree(result.getContent());
        assertThat(payload.path("type").asText()).isEqualTo("quality-queue");
        assertThat(payload.path("sources").get(0).path("type").asText()).isEqualTo("系统数据");
        assertThat(payload.path("metrics").get(0).path("label").asText()).isEqualTo("待复核");
        assertThat(payload.path("metrics").get(0).path("value").asInt()).isEqualTo(1);
        assertThat(payload.path("tasks").get(0).path("taskId").asText()).isEqualTo("det_20260611_151200_abcd1234");
        assertThat(payload.path("tasks").get(0).path("severity").asText()).isEqualTo("HIGH");
    }

    private DetectionAgentServiceImpl newService() {
        return newService(new ChatAssistantProperties());
    }

    private DetectionAgentServiceImpl newService(ChatAssistantProperties properties) {
        return new DetectionAgentServiceImpl(
                detectionTaskMapper,
                deepSeekClient,
                detectionTaskService,
                chatSessionService,
                ossStorageService,
                uploadAsyncService,
                detectionTaskDispatchService,
                new DetectionTaskAccessPolicy(),
                new ObjectMapper(),
                properties
        );
    }

    @Test
    void answerReturnsBatchTraceBusinessCard() throws Exception {
        String batchNo = "2026-06-11_SH_CAM01_A";
        when(detectionTaskService.getBatchTraceReport(batchNo)).thenReturn(Map.of(
                "batchNo", batchNo,
                "summary", Map.of(
                        "taskCount", 2,
                        "devices", List.of("CAM-01"),
                        "models", List.of("YOLO-v8"),
                        "workOrders", List.of("WO-001")
                ),
                "inspection", Map.of(
                        "totalImages", 30,
                        "defectCount", 4,
                        "confirmedDefectCount", 3,
                        "defectRate", 0.1333
                ),
                "quality", Map.of(
                        "pendingReview", 1,
                        "disposed", 1,
                        "reworkRequired", 1,
                        "recheckRequired", 0,
                        "closureRate", 0.5
                ),
                "distribution", Map.of(),
                "timeRange", Map.of(),
                "records", List.of(Map.of(
                        "taskId", "det_20260611_151200_abcd1234",
                        "workOrderNo", "WO-001",
                        "deviceName", "CAM-01",
                        "status", "COMPLETED",
                        "flowStatus", "REWORK_REQUIRED",
                        "reviewStatus", "PENDING",
                        "defectCount", 4,
                        "maxDefectSeverity", "HIGH"
                ))
        ));

        DetectionAgentServiceImpl service = new DetectionAgentServiceImpl(
                detectionTaskMapper,
                deepSeekClient,
                detectionTaskService,
                chatSessionService,
                ossStorageService,
                uploadAsyncService,
                detectionTaskDispatchService,
                new DetectionTaskAccessPolicy(),
                new ObjectMapper(),
                new ChatAssistantProperties()
        );

        AgentExecutionResult result = service.answer("查询批次 2026-06-11_SH_CAM01_A 的追溯报告", "tester");

        assertThat(result.getMessageType()).isEqualTo("BUSINESS_CARD");
        assertThat(result.getIntent()).isEqualTo("DETECTION_QUERY");
        JsonNode payload = new ObjectMapper().readTree(result.getContent());
        assertThat(payload.path("type").asText()).isEqualTo("batch-trace");
        assertThat(payload.path("sources").get(0).path("type").asText()).isEqualTo("系统数据");
        assertThat(payload.path("sources").get(1).path("type").asText()).isEqualTo("模型结果");
        assertThat(payload.path("batchNo").asText()).isEqualTo(batchNo);
        assertThat(payload.path("route").asText()).contains("tab=batch-trace");
        assertThat(payload.path("metrics").get(0).path("label").asText()).isEqualTo("任务数");
        assertThat(payload.path("records").get(0).path("taskId").asText()).isEqualTo("det_20260611_151200_abcd1234");
    }

    @Test
    void answerReturnsWorkOrderTraceBusinessCard() throws Exception {
        String workOrderNo = "WO-20260611-001";
        when(detectionTaskService.getWorkOrderTraceReport(workOrderNo)).thenReturn(Map.of(
                "workOrderNo", workOrderNo,
                "summary", Map.of(
                        "taskCount", 2,
                        "batchNos", List.of("BATCH-A", "BATCH-B"),
                        "devices", List.of("CAM-01"),
                        "models", List.of("YOLO-v8")
                ),
                "inspection", Map.of(
                        "totalImages", 40,
                        "defectCount", 6,
                        "confirmedDefectCount", 5,
                        "defectRate", 0.15
                ),
                "quality", Map.of(
                        "pendingReview", 0,
                        "disposed", 1,
                        "reworkRequired", 1,
                        "recheckRequired", 0,
                        "closureRate", 0.5
                ),
                "distribution", Map.of(),
                "timeRange", Map.of(),
                "records", List.of(Map.of(
                        "taskId", "det_20260611_161200_abcd1234",
                        "batchNo", "BATCH-A",
                        "workOrderNo", workOrderNo,
                        "deviceName", "CAM-01",
                        "status", "COMPLETED",
                        "flowStatus", "REWORK_REQUIRED",
                        "reviewStatus", "REVIEWED",
                        "defectCount", 6,
                        "maxDefectSeverity", "HIGH"
                ))
        ));

        DetectionAgentServiceImpl service = new DetectionAgentServiceImpl(
                detectionTaskMapper,
                deepSeekClient,
                detectionTaskService,
                chatSessionService,
                ossStorageService,
                uploadAsyncService,
                detectionTaskDispatchService,
                new DetectionTaskAccessPolicy(),
                new ObjectMapper(),
                new ChatAssistantProperties()
        );

        AgentExecutionResult result = service.answer("查看工单号 WO-20260611-001 的检测闭环", "tester");

        assertThat(result.getMessageType()).isEqualTo("BUSINESS_CARD");
        JsonNode payload = new ObjectMapper().readTree(result.getContent());
        assertThat(payload.path("type").asText()).isEqualTo("work-order-trace");
        assertThat(payload.path("sources").get(0).path("type").asText()).isEqualTo("系统数据");
        assertThat(payload.path("workOrderNo").asText()).isEqualTo(workOrderNo);
        assertThat(payload.path("route").asText()).contains("tab=work-order-trace");
        assertThat(payload.path("route").asText()).contains("workOrderNo=WO-20260611-001");
        assertThat(payload.path("records").get(0).path("workOrderNo").asText()).isEqualTo(workOrderNo);
    }

    @Test
    void answerReturnsDefectGalleryBusinessCard() throws Exception {
        String batchNo = "BATCH-001";
        when(detectionTaskService.listDefectGallery("划痕", "CRITICAL", "CAM-01", batchNo, null, 1, 8))
                .thenReturn(Map.of(
                        "total", 1,
                        "defectType", "划痕",
                        "severityLevel", "CRITICAL",
                        "deviceName", "CAM-01",
                        "batchNo", batchNo,
                        "records", List.of(Map.of(
                                "taskId", "det_20260611_151200_abcd1234",
                                "batchNo", batchNo,
                                "workOrderNo", "WO-001",
                                "deviceName", "CAM-01",
                                "defectCount", 3,
                                "maxDefectSeverity", "CRITICAL",
                                "primaryDefectType", "划痕",
                                "reviewStatus", "PENDING",
                                "defectEvidence", List.of(Map.of(
                                        "type", "划痕",
                                        "confidence", 0.96,
                                        "severity", "CRITICAL"
                                ))
                        ))
                ));

        DetectionAgentServiceImpl service = new DetectionAgentServiceImpl(
                detectionTaskMapper,
                deepSeekClient,
                detectionTaskService,
                chatSessionService,
                ossStorageService,
                uploadAsyncService,
                detectionTaskDispatchService,
                new DetectionTaskAccessPolicy(),
                new ObjectMapper(),
                new ChatAssistantProperties()
        );

        AgentExecutionResult result = service.answer("查看批次 BATCH-001 设备 CAM-01 的严重划痕缺陷证据", "tester");

        assertThat(result.getMessageType()).isEqualTo("BUSINESS_CARD");
        assertThat(result.getIntent()).isEqualTo("DETECTION_QUERY");
        JsonNode payload = new ObjectMapper().readTree(result.getContent());
        assertThat(payload.path("type").asText()).isEqualTo("defect-gallery");
        assertThat(payload.path("sources").get(0).path("type").asText()).isEqualTo("模型结果");
        assertThat(payload.path("route").asText()).contains("tab=defect-gallery");
        assertThat(payload.path("route").asText()).contains("batchNo=BATCH-001");
        assertThat(payload.path("route").asText()).contains("severityLevel=CRITICAL");
        assertThat(payload.path("metrics").get(0).path("label").asText()).isEqualTo("证据任务");
        assertThat(payload.path("records").get(0).path("primaryDefectType").asText()).isEqualTo("划痕");
    }

    @Test
    void previewActionExplainsWorkOrderReworkRequiresConfirmation() {
        DetectionAgentServiceImpl service = newService();

        String preview = service.previewAction("将工单 WO-20260611-001 标记为返工");

        assertThat(preview).contains("工单", "WO-20260611-001", "返工", "确认");
    }

    @Test
    void executeConfirmedActionDisposesWorkOrderAsRework() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_20260611_151200_abcd1234");
        task.setWorkOrderNo("WO-20260611-001");
        task.setBatchNo("BATCH-001");

        when(detectionTaskMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(task));
        when(detectionTaskService.disposeTask(eq("det_20260611_151200_abcd1234"), any(DetectionDispositionRequest.class)))
                .thenReturn(DetectionTaskProgressResponse.builder()
                        .taskId("det_20260611_151200_abcd1234")
                        .workOrderNo("WO-20260611-001")
                        .flowStatus("REWORK_REQUIRED")
                        .dispositionAction("REWORK")
                        .message("质检处置已提交")
                        .build());

        DetectionAgentServiceImpl service = newService();

        AgentExecutionResult result = service.executeConfirmedAction(
                "将工单 WO-20260611-001 标记为返工",
                new TenantContext(1L, "tester"),
                "sess_demo"
        );

        assertThat(result.getIntent()).isEqualTo("DETECTION_ACTION");
        assertThat(result.getContent()).contains("已将工单", "WO-20260611-001", "返工", "来源：系统数据");
        verify(detectionTaskService).disposeTask(eq("det_20260611_151200_abcd1234"), any(DetectionDispositionRequest.class));
    }

    @Test
    void executeConfirmedActionAllowsForeignWorkOrderForOperator() {
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(
                        "alice",
                        "N/A",
                        List.of(new SimpleGrantedAuthority("ROLE_OPERATOR"))));

        DetectionTask task = new DetectionTask();
        task.setTaskId("det_20260611_151200_abcd1234");
        task.setWorkOrderNo("WO-20260611-001");
        task.setCreatedBy("bob");
        when(detectionTaskMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(task));
        when(detectionTaskService.disposeTask(eq("det_20260611_151200_abcd1234"), any(DetectionDispositionRequest.class)))
                .thenReturn(DetectionTaskProgressResponse.builder()
                        .taskId("det_20260611_151200_abcd1234")
                        .workOrderNo("WO-20260611-001")
                        .flowStatus("REWORK_REQUIRED")
                        .dispositionAction("REWORK")
                        .message("质检处置已提交")
                        .build());

        DetectionAgentServiceImpl service = newService();

        AgentExecutionResult result = service.executeConfirmedAction(
                "将工单 WO-20260611-001 标记为返工",
                new TenantContext(1L, "alice"),
                "sess_demo"
        );
        assertThat(result.getContent()).contains("已将工单", "返工");
        verify(detectionTaskService).disposeTask(any(), any());
    }

    @Test
    void answerAllowsForeignTaskForOperator() {
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(
                        "alice",
                        "N/A",
                        List.of(new SimpleGrantedAuthority("ROLE_OPERATOR"))));

        DetectionTask task = new DetectionTask();
        task.setTaskId("det_20260611_151200_abcd1234");
        task.setCreatedBy("bob");
        when(detectionTaskMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(task);

        DetectionAgentServiceImpl service = newService();

        assertThat(service.answer(
                "查询任务 det_20260611_151200_abcd1234",
                "alice"
        )).isNotNull();
    }
}
