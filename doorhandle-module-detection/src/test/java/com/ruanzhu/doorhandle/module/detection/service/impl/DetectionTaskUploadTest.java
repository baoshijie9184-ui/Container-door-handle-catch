package com.ruanzhu.doorhandle.module.detection.service.impl;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.dto.detection.CreateDetectionTaskRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.CreateDetectionTaskResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionCaptureInfo;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskProgressResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadFileRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadedFileItem;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.net.URL;
import java.time.LocalDateTime;
import java.util.Arrays;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class DetectionTaskUploadTest {

    private DetectionTaskServiceFixture fixture;

    @BeforeEach
    void setUp() {
        fixture = new DetectionTaskServiceFixture();
        fixture.setUp();
    }

    @AfterEach
    void tearDown() {
        fixture.tearDown();
    }

    @Test
    void getTaskProgressAllowsTaskOwnedByAnotherUser() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_private");
        task.setCreatedBy("bob");
        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken("alice", "N/A",
                        List.of(new SimpleGrantedAuthority("ROLE_OPERATOR")))
        );

        assertEquals("det_private", fixture.service.getTaskProgress("det_private").getTaskId());
    }

    @Test
    void createTaskBuildsTraceableOssKeyFromCaptureInfoAndRelativePath() throws Exception {
        DetectionCaptureInfo captureInfo = new DetectionCaptureInfo();
        captureInfo.setCaptureDate("2026-05-20");
        captureInfo.setRegion("上海");
        captureInfo.setCollector("张三");
        captureInfo.setDeviceName("海康Cam01");
        captureInfo.setImageFolderName("批次A");

        DetectionUploadFileRequest file = new DetectionUploadFileRequest();
        file.setFileName("img001.jpg");
        file.setContentType("image/jpeg");
        file.setRelativePath("2026-05-20/上海/张三/海康Cam01/批次A/车间A/相机2/img001.jpg");

        CreateDetectionTaskRequest request = new CreateDetectionTaskRequest();
        request.setTaskType("BATCH");
        request.setCaptureInfo(captureInfo);
        request.setFiles(List.of(file));
        request.setThreshold(BigDecimal.valueOf(0.55));

        ModelInfo modelInfo = new ModelInfo();
        modelInfo.setModelId(7);
        modelInfo.setVersion("v1");

        when(fixture.ossStorageService.isConfigured()).thenReturn(true);
        when(fixture.ossStorageService.normalizeBasePrefix()).thenReturn("detection");
        when(fixture.ossStorageService.generatePutUrl(any(), any(), any())).thenReturn(new URL("http://example.com/upload"));
        when(fixture.modelService.getAllModels()).thenReturn(List.of(modelInfo));

        CreateDetectionTaskResponse response = fixture.service.createTask(request);

        ArgumentCaptor<DetectionTask> taskCaptor = ArgumentCaptor.forClass(DetectionTask.class);
        verify(fixture.detectionTaskMapper).insert(taskCaptor.capture());
        DetectionTask savedTask = taskCaptor.getValue();

        assertEquals("2026-05-20", savedTask.getCaptureDate());
        assertEquals("上海", savedTask.getRegion());
        assertEquals("张三", savedTask.getCollector());
        assertEquals("海康Cam01", savedTask.getDeviceName());
        assertEquals("批次A", savedTask.getImageFolderName());
        assertEquals("detection/2026-05-20/上海/张三/海康Cam01/批次A/Original/", savedTask.getSourceOssPrefix());

        String objectKey = response.getUploadUrls().get(0).getObjectKey();
        assertTrue(objectKey.startsWith(savedTask.getSourceOssPrefix()));
        assertTrue(objectKey.endsWith("车间A/相机2/img001.jpg"));
    }

    @Test
    void createTaskAssignsBatchWorkOrderAndInitialFlowStatus() throws Exception {
        DetectionCaptureInfo captureInfo = new DetectionCaptureInfo();
        captureInfo.setCaptureDate("2026-05-20");
        captureInfo.setRegion("上海");
        captureInfo.setCollector("张三");
        captureInfo.setDeviceName("CAM-01");
        captureInfo.setImageFolderName("批次A");

        DetectionUploadFileRequest file = new DetectionUploadFileRequest();
        file.setFileName("img001.jpg");
        file.setContentType("image/jpeg");

        CreateDetectionTaskRequest request = new CreateDetectionTaskRequest();
        request.setCaptureInfo(captureInfo);
        request.setFiles(List.of(file));

        when(fixture.ossStorageService.isConfigured()).thenReturn(true);
        when(fixture.ossStorageService.normalizeBasePrefix()).thenReturn("detection");
        when(fixture.ossStorageService.generatePutUrl(any(), any(), any())).thenReturn(new URL("http://example.com/upload"));
        when(fixture.modelService.getAllModels()).thenReturn(List.of());

        fixture.service.createTask(request);

        ArgumentCaptor<DetectionTask> taskCaptor = ArgumentCaptor.forClass(DetectionTask.class);
        verify(fixture.detectionTaskMapper).insert(taskCaptor.capture());
        DetectionTask savedTask = taskCaptor.getValue();

        assertEquals("2026-05-20_上海_CAM-01_批次A", savedTask.getBatchNo());
        assertTrue(savedTask.getWorkOrderNo().startsWith("WO-"));
        assertEquals("UPLOADING", savedTask.getFlowStatus());
    }

    @Test
    void createTaskIncrementsModelUsageStatsWhenModelSelected() throws Exception {
        DetectionCaptureInfo captureInfo = new DetectionCaptureInfo();
        captureInfo.setCaptureDate("2026-05-20");
        captureInfo.setRegion("上海");
        captureInfo.setCollector("张三");
        captureInfo.setDeviceName("海康Cam01");
        captureInfo.setImageFolderName("批次A");

        DetectionUploadFileRequest file = new DetectionUploadFileRequest();
        file.setFileName("img001.jpg");
        file.setContentType("image/jpeg");
        file.setRelativePath("img001.jpg");

        CreateDetectionTaskRequest request = new CreateDetectionTaskRequest();
        request.setTaskType("BATCH");
        request.setCaptureInfo(captureInfo);
        request.setFiles(List.of(file));
        request.setModelId(7);

        ModelInfo modelInfo = new ModelInfo();
        modelInfo.setModelId(7);
        modelInfo.setVersion("v1");
        when(fixture.ossStorageService.isConfigured()).thenReturn(true);
        when(fixture.ossStorageService.normalizeBasePrefix()).thenReturn("detection");
        when(fixture.ossStorageService.generatePutUrl(any(), any(), any())).thenReturn(new URL("http://example.com/upload"));
        when(fixture.modelInfoMapper.selectByModelId(7)).thenReturn(modelInfo);

        fixture.service.createTask(request);

        verify(fixture.modelService).incrementUsageStats(eq(7), any(LocalDateTime.class));
    }

    @Test
    void createTaskRejectsOversizedUploadFileBeforeGeneratingUrls() {
        ReflectionTestUtils.setField(fixture.service, "maxImageBytes", 4L);
        DetectionCaptureInfo captureInfo = new DetectionCaptureInfo();
        captureInfo.setCaptureDate("2026-05-20");
        captureInfo.setRegion("上海");
        captureInfo.setCollector("张三");
        captureInfo.setDeviceName("CAM-01");
        captureInfo.setImageFolderName("批次A");

        DetectionUploadFileRequest file = new DetectionUploadFileRequest();
        file.setFileName("img001.jpg");
        file.setContentType("image/jpeg");
        file.setFileSize(8L);

        CreateDetectionTaskRequest request = new CreateDetectionTaskRequest();
        request.setCaptureInfo(captureInfo);
        request.setFiles(List.of(file));

        when(fixture.ossStorageService.isConfigured()).thenReturn(true);

        BusinessException exception = assertThrows(BusinessException.class, () -> fixture.service.createTask(request));

        assertEquals("图片文件不能超过 4B", exception.getMessage());
    }

    @Test
    void createTaskRejectsUnsupportedUploadContentType() {
        DetectionCaptureInfo captureInfo = new DetectionCaptureInfo();
        captureInfo.setCaptureDate("2026-05-20");
        captureInfo.setRegion("上海");
        captureInfo.setCollector("张三");
        captureInfo.setDeviceName("CAM-01");
        captureInfo.setImageFolderName("批次A");

        DetectionUploadFileRequest file = new DetectionUploadFileRequest();
        file.setFileName("img001.jpg");
        file.setContentType("text/plain");

        CreateDetectionTaskRequest request = new CreateDetectionTaskRequest();
        request.setCaptureInfo(captureInfo);
        request.setFiles(List.of(file));

        when(fixture.ossStorageService.isConfigured()).thenReturn(true);

        BusinessException exception = assertThrows(BusinessException.class, () -> fixture.service.createTask(request));

        assertEquals("图片 Content-Type 不受支持: text/plain", exception.getMessage());
    }

    @Test
    void confirmUploadedRejectsObjectKeyOutsideTaskPrefix() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_001");
        task.setStatus("UPLOADING");
        task.setSourceOssPrefix("detection/2026/Original/");
        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);

        DetectionUploadedFileItem item = new DetectionUploadedFileItem();
        item.setFileName("img001.jpg");
        item.setObjectKey("other/2026/Original/img001.jpg");

        com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskUploadedRequest request =
                new com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskUploadedRequest();
        request.setUploadedFiles(List.of(item));

        BusinessException exception = assertThrows(
                BusinessException.class,
                () -> fixture.service.confirmUploaded("det_001", request)
        );

        assertEquals("上传文件对象 Key 不属于当前任务", exception.getMessage());
    }

    @Test
    void confirmUploadedRejectsBlankUploadedObjectKeys() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_001");
        task.setStatus("UPLOADING");
        task.setSourceOssPrefix("detection/2026/Original/");
        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);

        DetectionUploadedFileItem blankItem = new DetectionUploadedFileItem();
        blankItem.setFileName("img001.jpg");
        blankItem.setObjectKey(" ");

        com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskUploadedRequest request =
                new com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskUploadedRequest();
        request.setUploadedFiles(Arrays.asList(null, blankItem));

        BusinessException exception = assertThrows(
                BusinessException.class,
                () -> fixture.service.confirmUploaded("det_001", request)
        );

        assertEquals("上传文件对象 Key 不能为空", exception.getMessage());
    }

    @Test
    void confirmUploadedDoesNotDispatchTaskAlreadyClaimed() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_uploaded");
        task.setStatus("UPLOADED");
        task.setDispatchId("dispatch-existing");
        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);

        fixture.service.confirmUploaded("det_uploaded", new com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskUploadedRequest());

        verify(fixture.detectionTaskDispatchService, Mockito.never()).dispatchTaskAsync(any());
    }

    @Test
    void confirmUploadedDispatchesOnlyWhenConditionalClaimSucceeds() {
        DetectionTask task = new DetectionTask();
        task.setId(1L);
        task.setTaskId("det_claim");
        task.setStatus("UPLOADING");
        task.setSourceOssPrefix("detection/task/Original/");
        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);
        when(fixture.detectionTaskMapper.claimUploaded(any())).thenReturn(0);
        DetectionUploadedFileItem item = new DetectionUploadedFileItem();
        item.setFileName("a.jpg");
        item.setObjectKey("detection/task/Original/a.jpg");
        var request = new com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskUploadedRequest();
        request.setUploadedFiles(List.of(item));

        fixture.service.confirmUploaded("det_claim", request);

        verify(fixture.detectionTaskDispatchService, Mockito.never()).dispatchTaskAsync(any());
    }

    @Test
    void retryTaskResetsFailedTaskAndDispatchesAgain() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_retry");
        task.setStatus("FAILED");
        task.setStage("FAILED");
        task.setFlowStatus("FAILED");
        task.setOriginalImageKeysJson("[\"detection/source/img001.jpg\"]");
        task.setResultJsonOssKey("detection/result/result.json");
        task.setPreviewImageKeysJson("[\"detection/result/img001.jpg\"]");
        task.setStatisticsJson("{\"classCounts\":{\"Rusty\":1}}");
        task.setErrorMessage("worker timeout");
        task.setReviewStatus("REVIEWED");
        task.setDispositionStatus("DISPOSED");
        task.setRecheckRequired(true);
        task.setStartedAt(LocalDateTime.of(2026, 6, 10, 10, 0));
        task.setFinishedAt(LocalDateTime.of(2026, 6, 10, 10, 1));

        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);

        DetectionTaskProgressResponse response = fixture.service.retryTask("det_retry");

        assertEquals("UPLOADED", response.getStatus());
        assertEquals("PENDING_DETECTION", response.getFlowStatus());
        assertEquals("重新检测任务已提交", response.getMessage());

        ArgumentCaptor<DetectionTask> taskCaptor = ArgumentCaptor.forClass(DetectionTask.class);
        verify(fixture.detectionTaskMapper).updateById(taskCaptor.capture());
        DetectionTask retriedTask = taskCaptor.getValue();
        assertEquals("UPLOADED", retriedTask.getStatus());
        assertEquals("UPLOADED", retriedTask.getStage());
        assertEquals("PENDING_DETECTION", retriedTask.getFlowStatus());
        assertEquals("PENDING", retriedTask.getReviewStatus());
        assertEquals("PENDING", retriedTask.getDispositionStatus());
        assertEquals(Boolean.FALSE, retriedTask.getRecheckRequired());
        assertEquals(0, retriedTask.getProcessedImages());
        assertEquals(0, retriedTask.getSuccessfulImages());
        assertEquals(0, retriedTask.getFailedImages());
        assertEquals(null, retriedTask.getResultJsonOssKey());
        assertEquals(null, retriedTask.getPreviewImageKeysJson());
        assertEquals(null, retriedTask.getStatisticsJson());
        assertEquals(null, retriedTask.getErrorMessage());
        assertEquals(null, retriedTask.getStartedAt());
        assertEquals(null, retriedTask.getFinishedAt());
        verify(fixture.detectionTaskDispatchService).dispatchTaskAsync("det_retry");
    }

    @Test
    void retryTaskRejectsNonActionableTask() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_done");
        task.setStatus("COMPLETED");
        task.setFlowStatus("RELEASED");
        task.setOriginalImageKeysJson("[\"detection/source/img001.jpg\"]");

        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);

        BusinessException exception = assertThrows(
                BusinessException.class,
                () -> fixture.service.retryTask("det_done")
        );

        assertEquals("当前任务状态不支持重新检测", exception.getMessage());
    }

    @Test
    void markUploadedStoresUploadedKeysAndDispatchesDetection() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_mark_uploaded");
        task.setStatus("UPLOADING");
        task.setStage("UPLOADING");
        task.setFlowStatus("UPLOADING");
        task.setOriginalImageKeysJson("[\"old/key.jpg\"]");
        task.setTotalImages(1);

        DetectionUploadedFileItem uploaded = new DetectionUploadedFileItem();
        uploaded.setFileName("img001.jpg");
        uploaded.setObjectKey("detection/source/img001.jpg");

        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);
        when(fixture.detectionTaskMapper.claimUploaded(any())).thenReturn(1);

        fixture.service.markUploaded("det_mark_uploaded", List.of(uploaded));

        verify(fixture.detectionTaskMapper).claimUploaded(any());
        DetectionTask updatedTask = task;

        assertEquals("UPLOADED", updatedTask.getStatus());
        assertEquals("UPLOADED", updatedTask.getStage());
        assertEquals("PENDING_DETECTION", updatedTask.getFlowStatus());
        assertEquals(1, updatedTask.getTotalImages());
        assertTrue(updatedTask.getOriginalImageKeysJson().contains("detection/source/img001.jpg"));
        assertNotNull(updatedTask.getDispatchId());
        verify(fixture.detectionTaskDispatchService).dispatchTaskAsync("det_mark_uploaded");
    }
}
