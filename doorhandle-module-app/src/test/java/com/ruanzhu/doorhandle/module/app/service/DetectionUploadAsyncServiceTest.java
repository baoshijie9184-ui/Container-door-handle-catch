package com.ruanzhu.doorhandle.module.app.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.detection.dto.detection.CreateDetectionTaskResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadFileRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadUrlItem;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.service.DetectionTaskDispatchService;
import com.ruanzhu.doorhandle.module.infra.service.OssStorageService;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class DetectionUploadAsyncServiceTest {

    @Mock
    private DetectionTaskMapper detectionTaskMapper;

    @Mock
    private ChatSessionService chatSessionService;

    @Mock
    private OssStorageService ossStorageService;

    @Mock
    private DetectionTaskDispatchService detectionTaskDispatchService;

    @TempDir
    private Path tempDir;

    @Test
    void uploadAndConfirmMarksTaskFailedWhenNoImagesUploaded() {
        DetectionUploadAsyncService service = buildService();
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_upload_fail");
        when(detectionTaskMapper.selectOne(any())).thenReturn(task);

        service.uploadAndConfirm(
                new TenantContext(42L, "alice"),
                createResponse("det_upload_fail", "missing.jpg", "detection/task/Original/missing.jpg"),
                List.of(createFileRequest("missing.jpg")),
                tempDir,
                "session_1"
        );

        ArgumentCaptor<DetectionTask> taskCaptor = ArgumentCaptor.forClass(DetectionTask.class);
        verify(detectionTaskMapper).updateById(taskCaptor.capture());
        DetectionTask updatedTask = taskCaptor.getValue();

        assertEquals("FAILED", updatedTask.getStatus());
        assertEquals("FAILED", updatedTask.getStage());
        assertEquals("FAILED", updatedTask.getFlowStatus());
        assertEquals(0, updatedTask.getTotalImages());
        assertEquals("图片上传全部失败，未触发检测调度", updatedTask.getErrorMessage());
        verify(detectionTaskDispatchService, never()).dispatchTaskAsync(any());
        verify(chatSessionService).appendAssistantMessage(
                eq(new TenantContext(42L, "alice")), eq("session_1"), any(),
                eq("TEXT"), eq("DETECTION_ACTION"), eq(null));
    }

    @Test
    void uploadAndConfirmMarksTaskFailedWhenUploadPlanMismatches() throws Exception {
        DetectionUploadAsyncService service = buildService();
        Files.writeString(tempDir.resolve("img001.jpg"), "image-bytes");

        DetectionTask task = new DetectionTask();
        task.setTaskId("det_upload_plan_mismatch");
        when(detectionTaskMapper.selectOne(any())).thenReturn(task);

        CreateDetectionTaskResponse response = CreateDetectionTaskResponse.builder()
                .taskId("det_upload_plan_mismatch")
                .workflowUuid("wf_det_upload_plan_mismatch")
                .uploadUrls(List.of())
                .build();

        service.uploadAndConfirm(
                new TenantContext(42L, "alice"),
                response,
                List.of(createFileRequest("img001.jpg")),
                tempDir,
                "session_1"
        );

        ArgumentCaptor<DetectionTask> taskCaptor = ArgumentCaptor.forClass(DetectionTask.class);
        verify(detectionTaskMapper).updateById(taskCaptor.capture());
        DetectionTask updatedTask = taskCaptor.getValue();

        assertEquals("FAILED", updatedTask.getStatus());
        assertEquals("FAILED", updatedTask.getStage());
        assertEquals("FAILED", updatedTask.getFlowStatus());
        assertEquals(0, updatedTask.getTotalImages());
        assertEquals("上传地址列表不能为空", updatedTask.getErrorMessage());
        verify(ossStorageService, never()).putObject(any(), any(InputStream.class), anyLong(), any());
        verify(detectionTaskDispatchService, never()).dispatchTaskAsync(any());
        verify(chatSessionService).appendAssistantMessage(
                eq(new TenantContext(42L, "alice")), eq("session_1"), any(),
                eq("TEXT"), eq("DETECTION_ACTION"), eq(null));
    }

    @Test
    void uploadAndConfirmRejectsMismatchedUploadUrlFileName() throws Exception {
        DetectionUploadAsyncService service = buildService();
        Files.writeString(tempDir.resolve("img001.jpg"), "image-bytes");

        DetectionTask task = new DetectionTask();
        task.setTaskId("det_upload_name_mismatch");
        when(detectionTaskMapper.selectOne(any())).thenReturn(task);

        CreateDetectionTaskResponse response = createResponse(
                "det_upload_name_mismatch",
                "other.jpg",
                "detection/task/Original/other.jpg"
        );

        service.uploadAndConfirm(
                new TenantContext(42L, "alice"),
                response,
                List.of(createFileRequest("img001.jpg")),
                tempDir,
                null
        );

        ArgumentCaptor<DetectionTask> taskCaptor = ArgumentCaptor.forClass(DetectionTask.class);
        verify(detectionTaskMapper).updateById(taskCaptor.capture());
        DetectionTask updatedTask = taskCaptor.getValue();

        assertEquals("FAILED", updatedTask.getStatus());
        assertEquals("上传文件与上传地址不匹配", updatedTask.getErrorMessage());
        verify(ossStorageService, never()).putObject(any(), any(InputStream.class), anyLong(), any());
        verify(detectionTaskDispatchService, never()).dispatchTaskAsync(any());
    }

    @Test
    void uploadAndConfirmDispatchesOnlyAfterSuccessfulUpload() throws Exception {
        DetectionUploadAsyncService service = buildService();
        Files.writeString(tempDir.resolve("img001.jpg"), "image-bytes");

        DetectionTask task = new DetectionTask();
        task.setTaskId("det_upload_success");
        when(detectionTaskMapper.selectOne(any())).thenReturn(task);

        service.uploadAndConfirm(
                new TenantContext(42L, "alice"),
                createResponse("det_upload_success", "img001.jpg", "detection/task/Original/img001.jpg"),
                List.of(createFileRequest("img001.jpg")),
                tempDir,
                null
        );

        ArgumentCaptor<DetectionTask> taskCaptor = ArgumentCaptor.forClass(DetectionTask.class);
        verify(detectionTaskMapper).updateById(taskCaptor.capture());
        DetectionTask updatedTask = taskCaptor.getValue();

        assertEquals("UPLOADED", updatedTask.getStatus());
        assertEquals("UPLOADED", updatedTask.getStage());
        assertEquals("PENDING_DETECTION", updatedTask.getFlowStatus());
        assertEquals(1, updatedTask.getTotalImages());
        assertEquals("[\"detection/task/Original/img001.jpg\"]", updatedTask.getOriginalImageKeysJson());
        verify(ossStorageService).putObject(eq("detection/task/Original/img001.jpg"), any(InputStream.class), eq(11L), eq("image/jpeg"));
        verify(detectionTaskDispatchService).dispatchTaskAsync("det_upload_success");
    }

    @Test
    void uploadAndConfirmUsesRelativePathWhenFileNamesAreDuplicated() throws Exception {
        DetectionUploadAsyncService service = buildService();
        Files.createDirectories(tempDir.resolve("camera-a"));
        Files.createDirectories(tempDir.resolve("camera-b"));
        Files.writeString(tempDir.resolve("camera-a").resolve("img001.jpg"), "camera-a");
        Files.writeString(tempDir.resolve("camera-b").resolve("img001.jpg"), "camera-b");

        AtomicReference<String> uploadedContent = new AtomicReference<>();
        doAnswer(invocation -> {
            try (InputStream inputStream = invocation.getArgument(1)) {
                uploadedContent.set(new String(inputStream.readAllBytes(), StandardCharsets.UTF_8));
            }
            return null;
        }).when(ossStorageService).putObject(any(), any(InputStream.class), anyLong(), any());

        DetectionTask task = new DetectionTask();
        task.setTaskId("det_relative_path");
        when(detectionTaskMapper.selectOne(any())).thenReturn(task);

        service.uploadAndConfirm(
                new TenantContext(42L, "alice"),
                createResponse("det_relative_path", "img001.jpg", "detection/task/Original/camera-b/img001.jpg"),
                List.of(createFileRequest("img001.jpg", "camera-b/img001.jpg")),
                tempDir,
                null
        );

        assertEquals("camera-b", uploadedContent.get());
        verify(detectionTaskDispatchService).dispatchTaskAsync("det_relative_path");
    }

    @Test
    void uploadAndConfirmStoresUploadedKeysInOriginalPlanOrder() throws Exception {
        DetectionUploadAsyncService service = buildService();
        Files.writeString(tempDir.resolve("img001.jpg"), "image-one");
        Files.writeString(tempDir.resolve("img002.jpg"), "image-two");

        doAnswer(invocation -> {
            String objectKey = invocation.getArgument(0);
            if (objectKey.endsWith("img001.jpg")) {
                Thread.sleep(200L);
            }
            return null;
        }).when(ossStorageService).putObject(any(), any(InputStream.class), anyLong(), any());

        DetectionTask task = new DetectionTask();
        task.setTaskId("det_ordered_upload");
        when(detectionTaskMapper.selectOne(any())).thenReturn(task);

        CreateDetectionTaskResponse response = CreateDetectionTaskResponse.builder()
                .taskId("det_ordered_upload")
                .workflowUuid("wf_det_ordered_upload")
                .uploadUrls(List.of(
                        DetectionUploadUrlItem.builder()
                                .fileName("img001.jpg")
                                .objectKey("detection/task/Original/img001.jpg")
                                .putUrl("http://example.com/upload1")
                                .build(),
                        DetectionUploadUrlItem.builder()
                                .fileName("img002.jpg")
                                .objectKey("detection/task/Original/img002.jpg")
                                .putUrl("http://example.com/upload2")
                                .build()
                ))
                .build();

        service.uploadAndConfirm(
                new TenantContext(42L, "alice"),
                response,
                List.of(createFileRequest("img001.jpg"), createFileRequest("img002.jpg")),
                tempDir,
                null
        );

        ArgumentCaptor<DetectionTask> taskCaptor = ArgumentCaptor.forClass(DetectionTask.class);
        verify(detectionTaskMapper).updateById(taskCaptor.capture());

        assertEquals(
                "[\"detection/task/Original/img001.jpg\",\"detection/task/Original/img002.jpg\"]",
                taskCaptor.getValue().getOriginalImageKeysJson()
        );
        verify(detectionTaskDispatchService).dispatchTaskAsync("det_ordered_upload");
    }

    private DetectionUploadAsyncService buildService() {
        return new DetectionUploadAsyncService(
                detectionTaskMapper,
                chatSessionService,
                ossStorageService,
                new ObjectMapper(),
                detectionTaskDispatchService
        );
    }

    private CreateDetectionTaskResponse createResponse(String taskId, String fileName, String objectKey) {
        return CreateDetectionTaskResponse.builder()
                .taskId(taskId)
                .workflowUuid("wf_" + taskId)
                .uploadUrls(List.of(DetectionUploadUrlItem.builder()
                        .fileName(fileName)
                        .objectKey(objectKey)
                        .putUrl("http://example.com/upload")
                        .build()))
                .build();
    }

    private DetectionUploadFileRequest createFileRequest(String fileName) {
        return createFileRequest(fileName, null);
    }

    private DetectionUploadFileRequest createFileRequest(String fileName, String relativePath) {
        DetectionUploadFileRequest request = new DetectionUploadFileRequest();
        request.setFileName(fileName);
        request.setContentType("image/jpeg");
        request.setRelativePath(relativePath);
        return request;
    }
}
