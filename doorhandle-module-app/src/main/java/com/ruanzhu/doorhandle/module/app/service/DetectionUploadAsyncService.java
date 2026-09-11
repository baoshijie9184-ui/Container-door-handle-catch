package com.ruanzhu.doorhandle.module.app.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.detection.dto.detection.CreateDetectionTaskResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadFileRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadUrlItem;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadedFileItem;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.infra.service.OssStorageService;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import com.ruanzhu.doorhandle.module.detection.service.DetectionTaskDispatchService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Stream;

@Slf4j
@Service
@RequiredArgsConstructor
public class DetectionUploadAsyncService {

    private final DetectionTaskMapper detectionTaskMapper;
    private final ChatSessionService chatSessionService;
    private final OssStorageService ossStorageService;
    private final ObjectMapper objectMapper;
    private final DetectionTaskDispatchService detectionTaskDispatchService;

    private static final int MAX_RETRIES = 3;
    private static final int PARALLEL_UPLOADS = 6;
    private static final long STAGGER_MS = 150;

    private static final ExecutorService UPLOAD_EXECUTOR = new ThreadPoolExecutor(
            PARALLEL_UPLOADS, PARALLEL_UPLOADS,
            60L, TimeUnit.SECONDS,
            new LinkedBlockingQueue<>(),
            r -> {
                Thread t = new Thread(r, "oss-uploader");
                t.setDaemon(true);
                return t;
            });

    @Async
    public void uploadAndConfirm(TenantContext tenant,
                                  CreateDetectionTaskResponse createResp,
                                  List<DetectionUploadFileRequest> files,
                                  Path folder, String sessionId) {
        List<DetectionUploadUrlItem> uploadUrls = createResp.getUploadUrls();
        List<DetectionUploadedFileItem> uploadedFiles = new ArrayList<>();
        int successCount = 0;
        int failCount = 0;

        try {
            String uploadPlanError = validateUploadPlan(files, uploadUrls, folder);
            if (uploadPlanError != null) {
                markUploadFailed(createResp.getTaskId(), uploadPlanError);
                if (sessionId != null) {
                    appendAssistantMessage(
                            tenant, sessionId,
                            buildUploadPlanFailureMessage(createResp, uploadPlanError),
                            "TEXT",
                            "DETECTION_ACTION",
                            null
                    );
                }
                return;
            }

            List<CompletableFuture<Void>> futures = new ArrayList<>();
            AtomicInteger successCounter = new AtomicInteger(0);
            AtomicInteger failCounter = new AtomicInteger(0);
            List<DetectionUploadedFileItem> uploadedFilesSync = Collections.synchronizedList(uploadedFiles);

            for (int i = 0; i < files.size(); i++) {
                final int idx = i;
                // 错峰提交，避免同时冲击 OSS
                if (i > 0 && STAGGER_MS > 0) {
                    try { Thread.sleep(STAGGER_MS); } catch (InterruptedException e) { break; }
                }
                CompletableFuture<Void> future = CompletableFuture.runAsync(() -> {
                    DetectionUploadFileRequest file = files.get(idx);
                    DetectionUploadUrlItem urlItem = uploadUrls.get(idx);

                    Path imagePath = resolveImagePath(folder, file);
                    if (imagePath == null || !Files.exists(imagePath)) {
                        log.warn("找不到文件: {}, relativePath={}", file.getFileName(), file.getRelativePath());
                        failCounter.incrementAndGet();
                        return;
                    }

                    long imageSize;
                    try {
                        imageSize = Files.size(imagePath);
                    } catch (IOException e) {
                        log.error("读取文件失败: {} — {}", file.getFileName(), e.getMessage());
                        failCounter.incrementAndGet();
                        return;
                    }

                    // 使用 OSS SDK 上传（内置连接池 + 重试 + 正确SSL）
                    String objectKey = urlItem.getObjectKey();
                    String contentType = file.getContentType();
                    Exception lastEx = null;
                    for (int retry = 0; retry < MAX_RETRIES; retry++) {
                        try (InputStream in = Files.newInputStream(imagePath)) {
                            ossStorageService.putObject(objectKey, in, imageSize, contentType);
                            uploadedFilesSync.add(buildUploadedFileItem(file, urlItem));
                            successCounter.incrementAndGet();
                            return;
                        } catch (Exception e) {
                            lastEx = e;
                            if (retry < MAX_RETRIES - 1) {
                                long delayMs = 1000L * (1L << retry); // 1s, 2s, 4s
                                log.warn("OSS SDK上传失败(重试 {}/{}): {} — {}，{}ms后重试",
                                        retry + 1, MAX_RETRIES, file.getFileName(), e.getMessage(), delayMs);
                                try { Thread.sleep(delayMs); } catch (InterruptedException ie) { Thread.currentThread().interrupt(); break; }
                            }
                        }
                    }
                    log.error("OSS SDK上传失败(已重试{}次): {} — {}", MAX_RETRIES, file.getFileName(),
                            lastEx != null ? lastEx.getMessage() : "unknown");
                    failCounter.incrementAndGet();
                }, UPLOAD_EXECUTOR);
                futures.add(future);
            }

            CompletableFuture.allOf(futures.toArray(new CompletableFuture[0])).join();
            successCount = successCounter.get();
            failCount = failCounter.get();

            saveUploadResult(createResp.getTaskId(), orderUploadedFiles(uploadedFiles, uploadUrls));

            String resultMsg = buildResultMessage(createResp, successCount, failCount, files.size());
            if (sessionId != null) {
                appendAssistantMessage(tenant, sessionId, resultMsg, "TEXT", "DETECTION_ACTION", null);
            }
        } catch (Exception e) {
            log.error("异步上传过程异常: taskId={}, error={}", createResp.getTaskId(), e.getMessage(), e);
            if (sessionId != null) {
                try {
                    String errMsg = "上传过程出现异常：" + e.getMessage()
                            + "\n已成功上传 " + successCount + "/" + safeFileCount(files) + " 张图片。"
                            + "\n任务ID：`" + createResp.getTaskId() + "`";
                    appendAssistantMessage(tenant, sessionId, errMsg, "TEXT", "DETECTION_ACTION", null);
                } catch (Exception ex) {
                    log.error("发送上传异常通知失败: {}", ex.getMessage());
                }
            }
        }
    }

    private void appendAssistantMessage(TenantContext tenant, String sessionId, String content,
                                        String messageType, String intent, String actionId) {
        chatSessionService.appendAssistantMessage(
                tenant, sessionId, content, messageType, intent, actionId);
    }

    private String validateUploadPlan(List<DetectionUploadFileRequest> files,
                                      List<DetectionUploadUrlItem> uploadUrls,
                                      Path folder) {
        if (folder == null) {
            return "本地图片目录不能为空";
        }
        if (files == null || files.isEmpty()) {
            return "上传文件列表不能为空";
        }
        if (uploadUrls == null || uploadUrls.isEmpty()) {
            return "上传地址列表不能为空";
        }
        if (files.size() != uploadUrls.size()) {
            return "上传文件数量与上传地址数量不一致";
        }
        for (int i = 0; i < files.size(); i++) {
            DetectionUploadFileRequest file = files.get(i);
            DetectionUploadUrlItem uploadUrl = uploadUrls.get(i);
            if (file == null || !hasText(file.getFileName())) {
                return "上传文件名不能为空";
            }
            if (uploadUrl == null || !hasText(uploadUrl.getObjectKey())) {
                return "上传地址对象 Key 不能为空";
            }
            if (hasText(uploadUrl.getFileName()) && !uploadUrl.getFileName().equals(file.getFileName())) {
                return "上传文件与上传地址不匹配";
            }
        }
        return null;
    }

    private void markUploadFailed(String taskId, String reason) {
        DetectionTask task = detectionTaskMapper.selectOne(new LambdaQueryWrapper<DetectionTask>()
                .eq(DetectionTask::getTaskId, taskId)
                .last("limit 1"));
        if (task == null) {
            log.warn("找不到任务: {}", taskId);
            return;
        }
        task.setOriginalImageKeysJson("[]");
        task.setTotalImages(0);
        task.setStatus("FAILED");
        task.setStage("FAILED");
        task.setFlowStatus("FAILED");
        task.setErrorMessage(reason);
        task.setUpdatedAt(LocalDateTime.now());
        detectionTaskMapper.updateById(task);
        log.warn("任务 {} 上传计划无效: {}", taskId, reason);
    }

    private List<DetectionUploadedFileItem> orderUploadedFiles(List<DetectionUploadedFileItem> uploadedFiles,
                                                               List<DetectionUploadUrlItem> uploadUrls) {
        Map<String, DetectionUploadedFileItem> uploadedByObjectKey = new HashMap<>();
        for (DetectionUploadedFileItem uploadedFile : uploadedFiles) {
            if (uploadedFile != null && hasText(uploadedFile.getObjectKey())) {
                uploadedByObjectKey.put(uploadedFile.getObjectKey(), uploadedFile);
            }
        }

        List<DetectionUploadedFileItem> ordered = new ArrayList<>();
        for (DetectionUploadUrlItem uploadUrl : uploadUrls) {
            if (uploadUrl == null || !hasText(uploadUrl.getObjectKey())) {
                continue;
            }
            DetectionUploadedFileItem uploadedFile = uploadedByObjectKey.get(uploadUrl.getObjectKey());
            if (uploadedFile != null) {
                ordered.add(uploadedFile);
            }
        }
        return ordered;
    }

    private void saveUploadResult(String taskId, List<DetectionUploadedFileItem> uploadedFiles) {
        try {
            DetectionTask task = detectionTaskMapper.selectOne(new LambdaQueryWrapper<DetectionTask>()
                    .eq(DetectionTask::getTaskId, taskId)
                    .last("limit 1"));
            if (task == null) {
                log.warn("找不到任务: {}", taskId);
                return;
            }

            List<String> uploadedKeys = uploadedFiles.stream()
                    .map(DetectionUploadedFileItem::getObjectKey)
                    .toList();

            task.setOriginalImageKeysJson(objectMapper.writeValueAsString(uploadedKeys));
            task.setTotalImages(uploadedFiles.size());
            if (uploadedFiles.isEmpty()) {
                task.setStatus("FAILED");
                task.setStage("FAILED");
                task.setFlowStatus("FAILED");
                task.setErrorMessage("图片上传全部失败，未触发检测调度");
                task.setUpdatedAt(LocalDateTime.now());
                detectionTaskMapper.updateById(task);
                log.warn("任务 {} 上传全部失败，未触发检测调度", taskId);
                return;
            }

            task.setStatus("UPLOADED");
            task.setStage("UPLOADED");
            task.setFlowStatus("PENDING_DETECTION");
            task.setErrorMessage(null);
            task.setUpdatedAt(LocalDateTime.now());
            detectionTaskMapper.updateById(task);

            // 上传完成后自动触发检测调度
            detectionTaskDispatchService.dispatchTaskAsync(taskId);

            log.info("任务 {} 上传结果已保存，共 {} 个文件，已触发检测调度", taskId, uploadedFiles.size());
        } catch (JsonProcessingException e) {
            log.error("序列化上传文件 key 失败: {}", e.getMessage());
        }
    }

    private String buildResultMessage(CreateDetectionTaskResponse createResp,
                                       int successCount, int failCount, int total) {
        StringBuilder sb = new StringBuilder();
        if (successCount == 0) {
            sb.append("上传失败：本次没有图片成功上传，检测任务已标记为失败，未进入模型检测。\n\n");
            sb.append("任务信息：\n");
            sb.append("- 任务ID：`").append(createResp.getTaskId()).append("`\n");
            sb.append("- 工作流UUID：`").append(createResp.getWorkflowUuid()).append("`\n\n");
            sb.append("建议检查本地图片路径、文件权限和 OSS 配置后重新创建检测任务。");
            return sb.toString();
        }
        sb.append("上传完成！共 ").append(successCount).append("/").append(total).append(" 张图片上传成功");
        if (failCount > 0) {
            sb.append("，").append(failCount).append(" 张失败");
        }
        sb.append("。\n\n");
        sb.append("任务信息：\n");
        sb.append("- 任务ID：`").append(createResp.getTaskId()).append("`\n");
        sb.append("- 工作流UUID：`").append(createResp.getWorkflowUuid()).append("`\n\n");
        sb.append("你可以通过以下方式继续：\n");
        sb.append("- 输入「检测任务 ").append(createResp.getTaskId()).append("」开始检测\n");
        sb.append("- 或输入「查看任务 ").append(createResp.getTaskId()).append("」查看详情");
        return sb.toString();
    }

    private String buildUploadPlanFailureMessage(CreateDetectionTaskResponse createResp, String reason) {
        return "上传失败：上传计划校验未通过，检测任务已标记为失败，未启动图片上传。\n\n"
                + "失败原因：" + reason + "\n\n"
                + "任务ID：`" + createResp.getTaskId() + "`";
    }

    private int safeFileCount(List<DetectionUploadFileRequest> files) {
        return files == null ? 0 : files.size();
    }

    private boolean hasText(String value) {
        return value != null && !value.isBlank();
    }

    private Path findFileInTree(Path root, String fileName) {
        try (Stream<Path> stream = Files.walk(root, 5)) {
            return stream.filter(Files::isRegularFile)
                    .filter(p -> p.getFileName().toString().equals(fileName))
                    .findFirst().orElse(null);
        } catch (IOException e) {
            return null;
        }
    }

    private Path resolveImagePath(Path folder, DetectionUploadFileRequest file) {
        Path root = folder.toAbsolutePath().normalize();
        if (file.getRelativePath() != null && !file.getRelativePath().isBlank()) {
            Path candidate = root.resolve(file.getRelativePath()).normalize();
            if (candidate.startsWith(root) && Files.isRegularFile(candidate)) {
                return candidate;
            }
            log.warn("相对路径无效或越界: taskFile={}, relativePath={}", file.getFileName(), file.getRelativePath());
        }

        Path direct = root.resolve(file.getFileName()).normalize();
        if (direct.startsWith(root) && Files.isRegularFile(direct)) {
            return direct;
        }
        return findFileInTree(root, file.getFileName());
    }

    private DetectionUploadedFileItem buildUploadedFileItem(DetectionUploadFileRequest file,
                                                             DetectionUploadUrlItem urlItem) {
        DetectionUploadedFileItem item = new DetectionUploadedFileItem();
        item.setFileName(file.getFileName());
        item.setObjectKey(urlItem.getObjectKey());
        return item;
    }
}
