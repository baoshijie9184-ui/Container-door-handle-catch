package com.ruanzhu.doorhandle.module.detection.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.infra.config.properties.OssProperties;
import com.ruanzhu.doorhandle.module.detection.dto.detection.CreateDetectionTaskRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.CreateDetectionTaskResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionCaptureInfo;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionDispositionRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionPreviewImage;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionReworkResultRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionReviewRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskAssignmentRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskTraceResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTraceEvent;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTraceImage;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskProgressResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskResultResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskUploadedRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadFileRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadUrlItem;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadedFileItem;
import com.ruanzhu.doorhandle.contracts.detection.DetectionTaskCreatedEvent;
import com.ruanzhu.doorhandle.contracts.detection.DetectionTaskEventCaptureInfo;
import com.ruanzhu.doorhandle.contracts.detection.DetectionTaskFinishedEvent;
import com.ruanzhu.doorhandle.module.detection.dto.detection.RemoteDetectionTaskResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.ResumeUploadRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.ResumeUploadResponse;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.model.mapper.ModelInfoMapper;
import com.ruanzhu.doorhandle.module.detection.service.DetectionNotificationPort;
import com.ruanzhu.doorhandle.module.detection.service.DetectionTaskDispatchService;
import com.ruanzhu.doorhandle.module.detection.service.DetectionTaskService;
import com.ruanzhu.doorhandle.module.model.service.ModelService;
import com.ruanzhu.doorhandle.module.infra.service.OssStorageService;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.text.Normalizer;
import java.time.Duration;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
public class DetectionTaskServiceImpl implements DetectionTaskService {

    private static final Set<String> SUPPORTED_REVIEW_CONCLUSIONS = Set.of(
            "CONFIRMED_DEFECT", "FALSE_POSITIVE", "NORMAL_RELEASE", "NEEDS_RECHECK"
    );
    private static final Set<String> SUPPORTED_SEVERITY_LEVELS = Set.of("MINOR", "MAJOR", "CRITICAL");
    private static final Set<String> SUPPORTED_DISPOSITION_ACTIONS = Set.of(
            "RELEASE", "REWORK", "RECHECK", "HOLD", "SCRAP"
    );
    private static final Set<String> DISPOSITION_FLOW_STATUSES = Set.of(
            "RELEASED", "REWORK_REQUIRED", "RECHECK_REQUIRED", "HOLD", "SCRAPPED"
    );
    private static final Set<String> SUPPORTED_UPLOAD_IMAGE_CONTENT_TYPES = Set.of(
            "image/jpeg", "image/png", "image/bmp", "image/x-ms-bmp", "application/octet-stream"
    );
    private static final Set<String> SUPPORTED_UPLOAD_IMAGE_EXTENSIONS = Set.of(".jpg", ".jpeg", ".png", ".bmp");

    private final DetectionTaskMapper detectionTaskMapper;
    private final ModelInfoMapper modelInfoMapper;
    private final ModelService modelService;
    private final OssStorageService ossStorageService;
    private final OssProperties ossProperties;
    private final DetectionTaskDispatchService detectionTaskDispatchService;
    private final DetectionNotificationPort detectionNotificationPort;
    private final ObjectMapper objectMapper;
    private final DetectionTaskAccessPolicy accessPolicy;

    @Value("${detection.max-images-per-batch:200}")
    private int maxImagesPerBatch;

    @Value("${detection.max-image-bytes:10485760}")
    private long maxImageBytes;

    @Override
    @CacheEvict(cacheNames = {"detection-task", "dashboard", "model"}, allEntries = true)
    public CreateDetectionTaskResponse createTask(CreateDetectionTaskRequest request) {
        if (!ossStorageService.isConfigured()) {
            throw new BusinessException("OSS 未配置，暂时无法创建云端检测任务");
        }
        if (request.getFiles() == null || request.getFiles().isEmpty()) {
            throw new BusinessException("请至少选择一张图片");
        }
        validateUploadFiles(request.getFiles());

        ModelInfo modelInfo = resolveModelInfo(request.getModelId());
        String taskId = buildTaskId();
        LocalDateTime now = LocalDateTime.now();
        DetectionCaptureInfo captureInfo = normalizeCaptureInfo(request.getCaptureInfo());
        String uploadPrefix = buildUploadPrefix(captureInfo);
        List<String> originalKeys = new ArrayList<>();
        List<DetectionUploadUrlItem> uploadUrls = new ArrayList<>();
        for (int i = 0; i < request.getFiles().size(); i++) {
            DetectionUploadFileRequest file = request.getFiles().get(i);
            String objectKey = uploadPrefix + buildObjectName(file);
            originalKeys.add(objectKey);
            URL putUrl = ossStorageService.generatePutUrl(
                    objectKey,
                    file.getContentType(),
                    Duration.ofMinutes(ossProperties.getUploadUrlExpireMinutes())
            );
            uploadUrls.add(DetectionUploadUrlItem.builder()
                    .fileName(file.getFileName())
                    .objectKey(objectKey)
                    .putUrl(putUrl.toString())
                    .build());
        }

        String workflowUuid = UUID.randomUUID().toString();

        DetectionTask task = new DetectionTask();
        task.setTaskId(taskId);
        task.setWorkflowUuid(workflowUuid);
        task.setTaskType(StringUtils.hasText(request.getTaskType()) ? request.getTaskType().toUpperCase(Locale.ROOT) : "BATCH");
        task.setBatchNo(buildBatchNo(captureInfo));
        task.setWorkOrderNo(buildWorkOrderNo());
        task.setFlowStatus("UPLOADING");
        task.setReviewStatus("PENDING");
        task.setStatus("UPLOADING");
        task.setStage("UPLOADING");
        task.setModelId(modelInfo != null ? modelInfo.getModelId() : null);
        task.setModelVersion(modelInfo != null ? modelInfo.getVersion() : null);
        task.setThreshold(request.getThreshold() == null ? BigDecimal.valueOf(0.5) : request.getThreshold());
        task.setCaptureDate(captureInfo.getCaptureDate());
        task.setRegion(captureInfo.getRegion());
        task.setCollector(captureInfo.getCollector());
        task.setDeviceName(captureInfo.getDeviceName());
        task.setImageFolderName(captureInfo.getImageFolderName());
        task.setTotalImages(request.getFiles().size());
        task.setProcessedImages(0);
        task.setSuccessfulImages(0);
        task.setFailedImages(0);
        task.setSourceOssPrefix(uploadPrefix);
        task.setOriginalImageKeysJson(writeJson(originalKeys));
        task.setSessionId(request.getSessionId());
        task.setCreatedBy(resolveCurrentUsername());
        task.setCreatedAt(now);
        task.setUpdatedAt(now);
        detectionTaskMapper.insert(task);
        if (modelInfo != null && modelInfo.getModelId() != null) {
            modelService.incrementUsageStats(modelInfo.getModelId(), now);
        }

        return CreateDetectionTaskResponse.builder()
                .taskId(taskId)
                .workflowUuid(workflowUuid)
                .status(task.getStatus())
                .batchNo(task.getBatchNo())
                .workOrderNo(task.getWorkOrderNo())
                .flowStatus(task.getFlowStatus())
                .uploadPrefix(uploadPrefix)
                .captureInfo(captureInfo)
                .uploadUrls(uploadUrls)
                .build();
    }

    @Override
    public ResumeUploadResponse resumeUpload(String taskId, ResumeUploadRequest request) {
        DetectionTask task = getTask(taskId);
        if (!"UPLOADING".equals(task.getStatus())) {
            throw new BusinessException("任务状态不支持续传，当前状态: " + task.getStatus());
        }

        String uploadPrefix = task.getSourceOssPrefix();
        validateUploadFiles(request.getFiles());
        List<DetectionUploadUrlItem> uploadUrls = new ArrayList<>();
        for (DetectionUploadFileRequest file : request.getFiles()) {
            String objectKey = uploadPrefix + buildObjectName(file);
            URL putUrl = ossStorageService.generatePutUrl(
                    objectKey,
                    file.getContentType(),
                    Duration.ofMinutes(ossProperties.getUploadUrlExpireMinutes())
            );
            uploadUrls.add(DetectionUploadUrlItem.builder()
                    .fileName(file.getFileName())
                    .objectKey(objectKey)
                    .putUrl(putUrl.toString())
                    .build());
        }

        return ResumeUploadResponse.builder()
                .taskId(taskId)
                .uploadUrls(uploadUrls)
                .build();
    }

    @Override
    @CacheEvict(cacheNames = {"detection-task", "dashboard", "model"}, allEntries = true)
    public DetectionTaskProgressResponse confirmUploaded(String taskId, DetectionTaskUploadedRequest request) {
        DetectionTask task = getTask(taskId);
        if (!Set.of("UPLOADING", "FAILED").contains(task.getStatus())) {
            return buildProgressResponse(task, "任务已进入检测阶段");
        }
        if (request == null || request.getUploadedFiles() == null || request.getUploadedFiles().isEmpty()) {
            throw new BusinessException("上传文件不能为空");
        }
        List<String> uploadedKeys = validateUploadedKeys(task, request.getUploadedFiles());
        String uploadedKeysJson = writeJson(uploadedKeys);
        Integer modelId = request.getModelId() != null ? request.getModelId() : task.getModelId();
        ModelInfo modelInfo = resolveModelInfo(modelId);
        String modelVersion = modelInfo != null ? modelInfo.getVersion() : null;
        BigDecimal threshold = request.getThreshold() == null ? task.getThreshold() : request.getThreshold();
        String dispatchId = UUID.randomUUID().toString();
        LocalDateTime now = LocalDateTime.now();

        DetectionTask claim = new DetectionTask();
        claim.setTaskId(taskId);
        claim.setOriginalImageKeysJson(uploadedKeysJson);
        claim.setModelId(modelId);
        claim.setModelVersion(modelVersion);
        claim.setThreshold(threshold);
        claim.setTotalImages(uploadedKeys.size());
        claim.setDispatchId(dispatchId);
        claim.setUpdatedAt(now);
        if (detectionTaskMapper.claimUploaded(claim) != 1) {
            return buildProgressResponse(getTask(taskId), "任务已进入检测阶段");
        }

        task.setOriginalImageKeysJson(uploadedKeysJson);
        task.setModelId(modelId);
        task.setModelVersion(modelVersion);
        task.setThreshold(threshold);
        task.setTotalImages(uploadedKeys.size());
        task.setStatus("UPLOADED");
        task.setStage("UPLOADED");
        task.setFlowStatus("PENDING_DETECTION");
        task.setDispatchId(dispatchId);
        task.setLastFinishedEventId(null);
        task.setErrorMessage(null);
        task.setUpdatedAt(now);

        detectionTaskDispatchService.dispatchTaskAsync(taskId);
        return buildProgressResponse(task, "原图上传完成，已开始提交远程检测任务");
    }

    @Override
    public DetectionTaskProgressResponse getTaskProgress(String taskId) {
        DetectionTask task = getTask(taskId);
        return buildProgressResponse(task, null);
    }

    @Override
    public DetectionTaskResultResponse getTaskResult(String taskId) {
        DetectionTask task = getTask(taskId);
        List<String> previewKeys = readJsonList(task.getPreviewImageKeysJson());
        List<String> originalKeys = readJsonList(task.getOriginalImageKeysJson());
        Map<String, String> originalByName = originalKeys.stream().collect(Collectors.toMap(
                this::extractFileName,
                key -> key,
                (left, right) -> left,
                LinkedHashMap::new
        ));

        List<DetectionPreviewImage> previewImages = previewKeys.stream()
                .limit(9)
                .map(key -> {
                    String imageName = extractFileName(key);
                    String originalKey = originalByName.get(imageName);
                    return DetectionPreviewImage.builder()
                            .imageName(imageName)
                            .annotatedUrl(signUrl(key))
                            .originalUrl(signUrl(originalKey))
                            .build();
                })
                .toList();

        return DetectionTaskResultResponse.builder()
                .taskId(task.getTaskId())
                .status(task.getStatus())
                .batchNo(task.getBatchNo())
                .workOrderNo(task.getWorkOrderNo())
                .flowStatus(task.getFlowStatus())
                .qualityStation(task.getQualityStation())
                .assignee(task.getAssignee())
                .assignmentRemark(task.getAssignmentRemark())
                .assignedAt(formatDateTime(task.getAssignedAt()))
                .dueAt(formatDateTime(task.getDueAt()))
                .captureInfo(buildCaptureInfo(task))
                .totalImages(defaultInt(task.getTotalImages()))
                .successfulImages(defaultInt(task.getSuccessfulImages()))
                .failedImages(defaultInt(task.getFailedImages()))
                .statistics(readJsonMap(task.getStatisticsJson()))
                .defectEvidence(readJsonMapList(task.getDefectEvidenceJson()))
                .defectCount(defaultInt(task.getDefectCount()))
                .primaryDefectType(task.getPrimaryDefectType())
                .maxDefectSeverity(task.getMaxDefectSeverity())
                .previewImages(previewImages)
                .resultJsonUrl(signUrl(task.getResultJsonOssKey()))
                .sourceOssPrefix(task.getSourceOssPrefix())
                .resultOssPrefix(task.getResultOssPrefix())
                .detectionStartedAt(formatDateTime(task.getStartedAt()))
                .detectionFinishedAt(formatDateTime(task.getFinishedAt()))
                .errorMessage(task.getErrorMessage())
                .reviewStatus(task.getReviewStatus())
                .reviewConclusion(task.getReviewConclusion())
                .severityLevel(task.getSeverityLevel())
                .confirmedDefectCount(defaultInt(task.getConfirmedDefectCount()))
                .falsePositiveCount(defaultInt(task.getFalsePositiveCount()))
                .reviewRemark(task.getReviewRemark())
                .reviewer(task.getReviewer())
                .reviewedAt(formatDateTime(task.getReviewedAt()))
                .dispositionStatus(task.getDispositionStatus())
                .dispositionAction(task.getDispositionAction())
                .dispositionRemark(task.getDispositionRemark())
                .dispositionOperator(task.getDispositionOperator())
                .disposedAt(formatDateTime(task.getDisposedAt()))
                .recheckRequired(Boolean.TRUE.equals(task.getRecheckRequired()))
                .reworkResult(task.getReworkResult())
                .reworkOperator(task.getReworkOperator())
                .reworkRemark(task.getReworkRemark())
                .reworkCompletedAt(formatDateTime(task.getReworkCompletedAt()))
                .build();
    }

    @Override
    public DetectionTaskTraceResponse getTaskTrace(String taskId) {
        DetectionTask task = getTask(taskId);
        return buildTraceResponse(task);
    }

    @Override
    public java.util.Map<String, Object> getQualityReport(String taskId) {
        DetectionTask task = getTask(taskId);
        List<DetectionTraceImage> originalImages = buildTraceImages(readJsonList(task.getOriginalImageKeysJson()));
        List<DetectionTraceImage> previewImages = buildTraceImages(readJsonList(task.getPreviewImageKeysJson()));

        java.util.Map<String, Object> report = new LinkedHashMap<>();
        report.put("reportType", "QUALITY_INSPECTION_REPORT");
        report.put("taskId", task.getTaskId());
        report.put("workflowUuid", task.getWorkflowUuid());
        report.put("batchNo", task.getBatchNo());
        report.put("workOrderNo", task.getWorkOrderNo());
        report.put("status", task.getStatus());
        report.put("flowStatus", task.getFlowStatus());
        report.put("generatedAt", formatDateTime(LocalDateTime.now()));
        report.put("capture", buildReportCaptureSection(task));
        report.put("model", buildReportModelSection(task));
        report.put("inspection", buildReportInspectionSection(task));
        report.put("assignment", buildReportAssignmentSection(task));
        report.put("review", buildReportReviewSection(task));
        report.put("disposition", buildReportDispositionSection(task));
        report.put("rework", buildReportReworkSection(task));
        report.put("evidence", buildReportEvidenceSection(task, originalImages, previewImages));
        report.put("timeline", buildTraceTimeline(task));
        return report;
    }

    private DetectionTaskTraceResponse buildTraceResponse(DetectionTask task) {
        List<DetectionTraceImage> originalImages = buildTraceImages(readJsonList(task.getOriginalImageKeysJson()));
        List<DetectionTraceImage> previewImages = buildTraceImages(readJsonList(task.getPreviewImageKeysJson()));

        return DetectionTaskTraceResponse.builder()
                .taskId(task.getTaskId())
                .workflowUuid(task.getWorkflowUuid())
                .batchNo(task.getBatchNo())
                .workOrderNo(task.getWorkOrderNo())
                .flowStatus(task.getFlowStatus())
                .qualityStation(task.getQualityStation())
                .assignee(task.getAssignee())
                .assignmentRemark(task.getAssignmentRemark())
                .assignedAt(formatDateTime(task.getAssignedAt()))
                .dueAt(formatDateTime(task.getDueAt()))
                .status(task.getStatus())
                .captureDate(task.getCaptureDate())
                .region(task.getRegion())
                .collector(task.getCollector())
                .deviceName(task.getDeviceName())
                .imageFolderName(task.getImageFolderName())
                .modelId(task.getModelId())
                .modelVersion(task.getModelVersion())
                .threshold(task.getThreshold())
                .totalImages(defaultInt(task.getTotalImages()))
                .successfulImages(defaultInt(task.getSuccessfulImages()))
                .failedImages(defaultInt(task.getFailedImages()))
                .sourceOssPrefix(task.getSourceOssPrefix())
                .resultOssPrefix(task.getResultOssPrefix())
                .resultJsonKey(task.getResultJsonOssKey())
                .resultJsonUrl(signUrl(task.getResultJsonOssKey()))
                .originalImages(originalImages)
                .previewImages(previewImages)
                .statistics(readJsonMap(task.getStatisticsJson()))
                .defectEvidence(readJsonMapList(task.getDefectEvidenceJson()))
                .defectCount(defaultInt(task.getDefectCount()))
                .primaryDefectType(task.getPrimaryDefectType())
                .maxDefectSeverity(task.getMaxDefectSeverity())
                .reviewStatus(task.getReviewStatus())
                .reviewConclusion(task.getReviewConclusion())
                .severityLevel(task.getSeverityLevel())
                .confirmedDefectCount(defaultInt(task.getConfirmedDefectCount()))
                .falsePositiveCount(defaultInt(task.getFalsePositiveCount()))
                .reviewRemark(task.getReviewRemark())
                .reviewer(task.getReviewer())
                .reviewedAt(formatDateTime(task.getReviewedAt()))
                .dispositionStatus(task.getDispositionStatus())
                .dispositionAction(task.getDispositionAction())
                .dispositionRemark(task.getDispositionRemark())
                .dispositionOperator(task.getDispositionOperator())
                .disposedAt(formatDateTime(task.getDisposedAt()))
                .recheckRequired(Boolean.TRUE.equals(task.getRecheckRequired()))
                .reworkResult(task.getReworkResult())
                .reworkOperator(task.getReworkOperator())
                .reworkRemark(task.getReworkRemark())
                .reworkCompletedAt(formatDateTime(task.getReworkCompletedAt()))
                .timeline(buildTraceTimeline(task))
                .build();
    }

    @Override
    public java.util.Map<String, Object> listTasks(int page, int size, String keyword, String status,
                                                    String collector, String deviceName, String region) {
        com.baomidou.mybatisplus.core.metadata.IPage<DetectionTask> taskPage = new com.baomidou.mybatisplus.extension.plugins.pagination.Page<>(page, size);
        LambdaQueryWrapper<DetectionTask> wrapper = new LambdaQueryWrapper<DetectionTask>()
                .orderByDesc(DetectionTask::getCreatedAt);
        applyOwnerFilter(wrapper);

        // 关键字搜索：任务ID、文件夹名、批次号或工单号
        if (org.springframework.util.StringUtils.hasText(keyword)) {
            wrapper.and(w -> w
                    .like(DetectionTask::getTaskId, keyword)
                    .or()
                    .like(DetectionTask::getImageFolderName, keyword)
                    .or()
                    .like(DetectionTask::getBatchNo, keyword)
                    .or()
                    .like(DetectionTask::getWorkOrderNo, keyword));
        }

        // 状态过滤
        if (org.springframework.util.StringUtils.hasText(status)) {
            wrapper.eq(DetectionTask::getStatus, status.toUpperCase());
        }

        // 采集人过滤
        if (org.springframework.util.StringUtils.hasText(collector)) {
            wrapper.like(DetectionTask::getCollector, collector);
        }

        // 设备名过滤
        if (org.springframework.util.StringUtils.hasText(deviceName)) {
            wrapper.like(DetectionTask::getDeviceName, deviceName);
        }

        // 地区过滤
        if (org.springframework.util.StringUtils.hasText(region)) {
            wrapper.like(DetectionTask::getRegion, region);
        }

        detectionTaskMapper.selectPage(taskPage, wrapper);
        List<DetectionTaskProgressResponse> records = taskPage.getRecords().stream()
                .map(task -> buildProgressResponse(task, null))
                .collect(Collectors.toList());

        java.util.Map<String, Object> result = new java.util.HashMap<>();
        result.put("records", records);
        result.put("total", taskPage.getTotal());
        return result;
    }

    @Override
    public java.util.Map<String, Object> listQualityQueue(String queue, int page, int size) {
        String normalizedQueue = normalizeQualityQueue(queue);
        com.baomidou.mybatisplus.core.metadata.IPage<DetectionTask> taskPage = new com.baomidou.mybatisplus.extension.plugins.pagination.Page<>(page, size);
        LambdaQueryWrapper<DetectionTask> wrapper = new LambdaQueryWrapper<DetectionTask>()
                .orderByDesc(DetectionTask::getUpdatedAt)
                .orderByDesc(DetectionTask::getCreatedAt);
        applyOwnerFilter(wrapper);
        applyQualityQueueFilter(wrapper, normalizedQueue);

        detectionTaskMapper.selectPage(taskPage, wrapper);
        List<DetectionTaskProgressResponse> records = taskPage.getRecords().stream()
                .map(task -> buildProgressResponse(task, null))
                .collect(Collectors.toList());

        java.util.Map<String, Object> result = new java.util.HashMap<>();
        result.put("queue", normalizedQueue);
        result.put("records", records);
        result.put("total", taskPage.getTotal());
        return result;
    }

    @Override
    public java.util.Map<String, Object> listDefectGallery(String defectType, String severityLevel, String deviceName,
                                                           String batchNo, Integer modelId, int page, int size) {
        com.baomidou.mybatisplus.core.metadata.IPage<DetectionTask> taskPage =
                new com.baomidou.mybatisplus.extension.plugins.pagination.Page<>(page, size);
        LambdaQueryWrapper<DetectionTask> wrapper = new LambdaQueryWrapper<DetectionTask>()
                .gt(DetectionTask::getDefectCount, 0)
                .orderByDesc(DetectionTask::getCreatedAt);
        applyOwnerFilter(wrapper);

        if (StringUtils.hasText(defectType)) {
            wrapper.eq(DetectionTask::getPrimaryDefectType, defectType.trim());
        }
        if (StringUtils.hasText(severityLevel)) {
            wrapper.eq(DetectionTask::getMaxDefectSeverity, severityLevel.trim().toUpperCase(Locale.ROOT));
        }
        if (StringUtils.hasText(deviceName)) {
            wrapper.like(DetectionTask::getDeviceName, deviceName.trim());
        }
        if (StringUtils.hasText(batchNo)) {
            wrapper.eq(DetectionTask::getBatchNo, batchNo.trim());
        }
        if (modelId != null) {
            wrapper.eq(DetectionTask::getModelId, modelId);
        }

        detectionTaskMapper.selectPage(taskPage, wrapper);
        List<DetectionTaskTraceResponse> records = taskPage.getRecords().stream()
                .map(this::buildTraceResponse)
                .collect(Collectors.toList());

        java.util.Map<String, Object> result = new LinkedHashMap<>();
        result.put("records", records);
        result.put("total", taskPage.getTotal());
        result.put("defectType", defectType);
        result.put("severityLevel", severityLevel);
        result.put("deviceName", deviceName);
        result.put("batchNo", batchNo);
        result.put("modelId", modelId);
        return result;
    }

    @Override
    public java.util.Map<String, Object> getBatchTraceReport(String batchNo) {
        if (!StringUtils.hasText(batchNo)) {
            throw new BusinessException("批次号不能为空");
        }
        String normalizedBatchNo = batchNo.trim();
        LambdaQueryWrapper<DetectionTask> wrapper = new LambdaQueryWrapper<DetectionTask>()
                .eq(DetectionTask::getBatchNo, normalizedBatchNo)
                .orderByAsc(DetectionTask::getCreatedAt);
        applyOwnerFilter(wrapper);
        List<DetectionTask> tasks = detectionTaskMapper.selectList(wrapper);
        if (tasks == null || tasks.isEmpty()) {
            throw new BusinessException(404, "批次不存在: " + normalizedBatchNo);
        }

        java.util.Map<String, Object> report = new LinkedHashMap<>();
        report.put("reportType", "BATCH_TRACE_REPORT");
        report.put("batchNo", normalizedBatchNo);
        report.put("generatedAt", formatDateTime(LocalDateTime.now()));
        report.put("summary", buildBatchSummary(tasks));
        report.put("inspection", buildBatchInspection(tasks));
        report.put("quality", buildBatchQuality(tasks));
        report.put("distribution", buildBatchDistribution(tasks));
        report.put("timeRange", buildBatchTimeRange(tasks));
        report.put("records", tasks.stream()
                .limit(50)
                .map(task -> buildProgressResponse(task, null))
                .collect(Collectors.toList()));
        return report;
    }

    @Override
    public java.util.Map<String, Object> getWorkOrderTraceReport(String workOrderNo) {
        if (!StringUtils.hasText(workOrderNo)) {
            throw new BusinessException("工单号不能为空");
        }
        String normalizedWorkOrderNo = workOrderNo.trim();
        LambdaQueryWrapper<DetectionTask> wrapper = new LambdaQueryWrapper<DetectionTask>()
                .eq(DetectionTask::getWorkOrderNo, normalizedWorkOrderNo)
                .orderByAsc(DetectionTask::getCreatedAt);
        applyOwnerFilter(wrapper);
        List<DetectionTask> tasks = detectionTaskMapper.selectList(wrapper);
        if (tasks == null || tasks.isEmpty()) {
            throw new BusinessException(404, "工单不存在: " + normalizedWorkOrderNo);
        }

        java.util.Map<String, Object> report = new LinkedHashMap<>();
        report.put("reportType", "WORK_ORDER_TRACE_REPORT");
        report.put("workOrderNo", normalizedWorkOrderNo);
        report.put("generatedAt", formatDateTime(LocalDateTime.now()));
        report.put("summary", buildWorkOrderSummary(tasks));
        report.put("inspection", buildBatchInspection(tasks));
        report.put("quality", buildBatchQuality(tasks));
        report.put("distribution", buildBatchDistribution(tasks));
        report.put("timeRange", buildBatchTimeRange(tasks));
        report.put("records", tasks.stream()
                .limit(50)
                .map(task -> buildProgressResponse(task, null))
                .collect(Collectors.toList()));
        return report;
    }

    @Override
    @CacheEvict(cacheNames = {"detection-task", "dashboard"}, allEntries = true)
    public DetectionTaskProgressResponse advanceTaskFlow(String taskId, String targetFlowStatus) {
        DetectionTask task = getTask(taskId);
        String normalizedTarget = normalizeFlowStatus(targetFlowStatus);
        validateFlowTransition(task.getFlowStatus(), normalizedTarget);

        task.setFlowStatus(normalizedTarget);
        task.setUpdatedAt(LocalDateTime.now());
        detectionTaskMapper.updateById(task);
        return buildProgressResponse(task, "任务已流转到 " + normalizedTarget);
    }

    @Override
    @CacheEvict(cacheNames = {"detection-task", "dashboard"}, allEntries = true)
    public DetectionTaskProgressResponse assignQualityTask(String taskId, DetectionTaskAssignmentRequest request) {
        DetectionTask task = getTask(taskId);
        if (!"COMPLETED".equals(task.getStatus()) && !"PARTIAL_FAILED".equals(task.getStatus())) {
            throw new BusinessException("只有已完成检测任务才能分派质检");
        }
        if (isFinalQualityClosed(task)) {
            throw new BusinessException("已关闭任务不能重新分派质检");
        }
        if (request == null || !StringUtils.hasText(request.getQualityStation()) || !StringUtils.hasText(request.getAssignee())) {
            throw new BusinessException("质检站点和责任人不能为空");
        }

        LocalDateTime now = LocalDateTime.now();
        task.setQualityStation(request.getQualityStation().trim());
        task.setAssignee(request.getAssignee().trim());
        task.setAssignmentRemark(request.getAssignmentRemark());
        task.setAssignedAt(now);
        task.setDueAt(parseDateTime(request.getDueAt(), null));
        if (!"REWORK_REQUIRED".equals(task.getFlowStatus())) {
            task.setFlowStatus("REVIEWING");
        }
        task.setUpdatedAt(now);
        detectionTaskMapper.updateById(task);
        return buildProgressResponse(task, "质检任务已分派");
    }

    @Override
    @CacheEvict(cacheNames = {"detection-task", "dashboard"}, allEntries = true)
    public DetectionTaskProgressResponse reviewTask(String taskId, DetectionReviewRequest request) {
        DetectionTask task = getTask(taskId);
        if (!"COMPLETED".equals(task.getStatus()) && !"PARTIAL_FAILED".equals(task.getStatus())) {
            throw new BusinessException("只有已完成检测任务才能复核");
        }
        if (isQualityDisposed(task)) {
            throw new BusinessException("已处置任务不能重复复核");
        }

        String reviewConclusion = normalizeReviewConclusion(request == null ? null : request.getReviewConclusion());
        String severityLevel = normalizeSeverityLevel(request == null ? null : request.getSeverityLevel());
        int confirmedDefectCount = defaultInt(request == null ? null : request.getConfirmedDefectCount());
        int falsePositiveCount = defaultInt(request == null ? null : request.getFalsePositiveCount());
        validateReviewPayload(reviewConclusion, severityLevel, confirmedDefectCount, falsePositiveCount);

        task.setReviewStatus("REVIEWED");
        task.setReviewConclusion(reviewConclusion);
        task.setSeverityLevel(severityLevel);
        task.setConfirmedDefectCount(confirmedDefectCount);
        task.setFalsePositiveCount(falsePositiveCount);
        task.setReviewRemark(request == null ? null : request.getReviewRemark());
        task.setReviewer(resolveCurrentUsername());
        task.setReviewedAt(LocalDateTime.now());
        task.setFlowStatus("CONFIRMED");
        task.setUpdatedAt(LocalDateTime.now());
        detectionTaskMapper.updateById(task);
        return buildProgressResponse(task, "人工复核已完成");
    }

    @Override
    @CacheEvict(cacheNames = {"detection-task", "dashboard"}, allEntries = true)
    public DetectionTaskProgressResponse disposeTask(String taskId, DetectionDispositionRequest request) {
        DetectionTask task = getTask(taskId);
        validateDispositionReady(task);

        String action = normalizeDispositionAction(request == null ? null : request.getDispositionAction());
        validateDispositionAction(task, action);

        LocalDateTime now = LocalDateTime.now();
        task.setDispositionStatus("DISPOSED");
        task.setDispositionAction(action);
        task.setDispositionRemark(request == null ? null : request.getDispositionRemark());
        task.setDispositionOperator(resolveCurrentUsername());
        task.setDisposedAt(now);
        task.setRecheckRequired("RECHECK".equals(action) || Boolean.TRUE.equals(request == null ? null : request.getRecheckRequired()));
        task.setFlowStatus(resolveDispositionFlowStatus(action, task.getRecheckRequired()));
        task.setUpdatedAt(now);
        detectionTaskMapper.updateById(task);

        return buildProgressResponse(task, "质检处置已完成: " + action);
    }

    @Override
    @CacheEvict(cacheNames = {"detection-task", "dashboard"}, allEntries = true)
    public DetectionTaskProgressResponse submitReworkResult(String taskId, DetectionReworkResultRequest request) {
        DetectionTask task = getTask(taskId);
        if (!"REWORK_REQUIRED".equals(task.getFlowStatus())) {
            throw new BusinessException("只有待返工任务才能回填返工结果");
        }
        if (request == null || !StringUtils.hasText(request.getReworkResult())) {
            throw new BusinessException("返工结果不能为空");
        }

        LocalDateTime now = LocalDateTime.now();
        boolean recheckRequired = Boolean.TRUE.equals(request.getRecheckRequired());
        task.setReworkResult(request.getReworkResult().trim());
        task.setReworkOperator(StringUtils.hasText(request.getReworkOperator())
                ? request.getReworkOperator().trim()
                : resolveCurrentUsername());
        task.setReworkRemark(request.getReworkRemark());
        task.setReworkCompletedAt(now);
        task.setRecheckRequired(recheckRequired);
        task.setReviewStatus("PENDING");
        task.setDispositionStatus(null);
        task.setDispositionAction(null);
        task.setDispositionRemark(null);
        task.setDispositionOperator(null);
        task.setDisposedAt(null);
        task.setFlowStatus(recheckRequired ? "RECHECK_REQUIRED" : "PENDING_REVIEW");
        task.setUpdatedAt(now);
        detectionTaskMapper.updateById(task);
        return buildProgressResponse(task, recheckRequired ? "返工结果已提交，等待复检" : "返工结果已提交，等待复核");
    }

    @Override
    @CacheEvict(cacheNames = {"detection-task", "dashboard", "model"}, allEntries = true)
    public DetectionTaskProgressResponse retryTask(String taskId) {
        DetectionTask task = getTask(taskId);
        validateRetryable(task);

        LocalDateTime now = LocalDateTime.now();
        task.setStatus("UPLOADED");
        task.setStage("UPLOADED");
        task.setFlowStatus("PENDING_DETECTION");
        task.setProcessedImages(0);
        task.setSuccessfulImages(0);
        task.setFailedImages(0);
        task.setResultOssPrefix(null);
        task.setResultJsonOssKey(null);
        task.setPreviewImageKeysJson(null);
        task.setStatisticsJson(null);
        task.setDefectEvidenceJson(null);
        task.setDefectCount(0);
        task.setPrimaryDefectType(null);
        task.setMaxDefectSeverity(null);
        task.setErrorMessage(null);
        task.setReviewStatus("PENDING");
        task.setReviewConclusion(null);
        task.setSeverityLevel(null);
        task.setConfirmedDefectCount(0);
        task.setFalsePositiveCount(0);
        task.setReviewRemark(null);
        task.setReviewer(null);
        task.setReviewedAt(null);
        task.setDispositionStatus("PENDING");
        task.setDispositionAction(null);
        task.setDispositionRemark(null);
        task.setDispositionOperator(null);
        task.setDisposedAt(null);
        task.setRecheckRequired(false);
        task.setStartedAt(null);
        task.setFinishedAt(null);
        task.setDispatchId(UUID.randomUUID().toString());
        task.setLastFinishedEventId(null);
        task.setUpdatedAt(now);
        detectionTaskMapper.updateById(task);

        detectionTaskDispatchService.dispatchTaskAsync(taskId);
        return buildProgressResponse(task, "重新检测任务已提交");
    }

    @Override
    @CacheEvict(cacheNames = {"detection-task", "dashboard"}, allEntries = true)
    public void markUploaded(String taskId, List<DetectionUploadedFileItem> uploadedFiles) {
        DetectionTaskUploadedRequest request = new DetectionTaskUploadedRequest();
        request.setUploadedFiles(uploadedFiles);
        confirmUploaded(taskId, request);
    }

    public DetectionCaptureInfo buildCaptureInfo(DetectionTask task) {
        DetectionCaptureInfo captureInfo = new DetectionCaptureInfo();
        captureInfo.setCaptureDate(task.getCaptureDate());
        captureInfo.setRegion(task.getRegion());
        captureInfo.setCollector(task.getCollector());
        captureInfo.setDeviceName(task.getDeviceName());
        captureInfo.setImageFolderName(task.getImageFolderName());
        return captureInfo;
    }

    public DetectionTaskCreatedEvent buildCreatedEvent(DetectionTask task) {
        return DetectionTaskCreatedEvent.builder()
                .eventId(UUID.randomUUID().toString())
                .eventType("DETECTION_TASK_CREATED")
                .eventTime(OffsetDateTime.now(ZoneOffset.ofHours(8)).toString())
                .taskId(task.getTaskId())
                .dispatchId(task.getDispatchId())
                .bucketName(getBucketName())
                .sourcePrefix(task.getSourceOssPrefix())
                .originalKeys(readJsonList(task.getOriginalImageKeysJson()))
                .captureInfo(toEventCaptureInfo(task))
                .modelId(task.getModelId())
                .threshold(task.getThreshold())
                .build();
    }

    @CacheEvict(cacheNames = {"detection-task", "dashboard", "model"}, allEntries = true)
    public void completeTask(String taskId, RemoteDetectionTaskResponse response) {
        DetectionTask task = getTaskForSystem(taskId);
        applyFinishedEvent(DetectionTaskFinishedEvent.builder()
                .eventId(UUID.randomUUID().toString())
                .taskId(taskId)
                .dispatchId(task.getDispatchId())
                .status(response != null ? response.getStatus() : null)
                .resultOssPrefix(response != null ? response.getResultOssPrefix() : null)
                .resultJsonKey(response != null ? response.getResultJsonKey() : null)
                .previewKeys(response != null ? response.getPreviewKeys() : Collections.emptyList())
                .statistics(response != null ? response.getStatistics() : Collections.emptyMap())
                .defectEvidence(response != null ? response.getDefectEvidence() : Collections.emptyList())
                .totalImages(response != null ? response.getTotalImages() : null)
                .successfulImages(response != null ? response.getSuccessfulImages() : 0)
                .failedImages(response != null ? response.getFailedImages() : 0)
                .errorMessage(response != null ? response.getErrorMessage() : null)
                .build());
    }

    @Transactional
    @CacheEvict(cacheNames = {"detection-task", "dashboard"}, allEntries = true)
    public void applyFinishedEvent(DetectionTaskFinishedEvent event) {
        DetectionTask task = getTaskForSystemLocked(event.getTaskId());
        boolean staleDispatch = StringUtils.hasText(task.getDispatchId())
                && !Objects.equals(task.getDispatchId(), event.getDispatchId());
        boolean duplicateEvent = StringUtils.hasText(event.getEventId())
                && Objects.equals(task.getLastFinishedEventId(), event.getEventId());
        if (staleDispatch || duplicateEvent) {
            log.info("忽略过期或重复的检测完成事件: taskId={}, dispatchId={}, eventId={}",
                    event.getTaskId(), event.getDispatchId(), event.getEventId());
            return;
        }
        task.setStage("UPLOADING_RESULT");
        task.setStatus("UPLOADING_RESULT");
        task.setUpdatedAt(LocalDateTime.now());
        if (StringUtils.hasText(event.getEventId())) {
            task.setLastFinishedEventId(event.getEventId());
        }
        detectionTaskMapper.updateById(task);

        task.setProcessedImages(event.getTotalImages() != null ? event.getTotalImages() : task.getTotalImages());
        task.setSuccessfulImages(event.getSuccessfulImages() != null ? event.getSuccessfulImages() : 0);
        task.setFailedImages(event.getFailedImages() != null ? event.getFailedImages() : 0);
        task.setResultJsonOssKey(event.getResultJsonKey());
        task.setResultOssPrefix(event.getResultOssPrefix());
        task.setPreviewImageKeysJson(writeJson(event.getPreviewKeys() != null ? event.getPreviewKeys() : Collections.emptyList()));
        task.setStatisticsJson(writeJson(event.getStatistics() != null ? event.getStatistics() : Collections.emptyMap()));
        applyDefectEvidence(task, event);
        task.setErrorMessage(event.getErrorMessage());
        task.setStartedAt(parseDateTime(event.getStartedAt(), task.getStartedAt()));
        task.setFinishedAt(parseFinishedAt(event.getFinishedAt()));
        task.setUpdatedAt(LocalDateTime.now());

        String remoteStatus = event.getStatus();
        boolean hasQualityDecision = hasQualityDecision(task);
        if ("partial_failed".equalsIgnoreCase(remoteStatus)) {
            task.setStatus("PARTIAL_FAILED");
            task.setStage("PARTIAL_FAILED");
            resetQualityWorkflowIfUnreviewed(task, hasQualityDecision);
        } else if ("success".equalsIgnoreCase(remoteStatus) || "completed".equalsIgnoreCase(remoteStatus)) {
            task.setStatus("COMPLETED");
            task.setStage("COMPLETED");
            resetQualityWorkflowIfUnreviewed(task, hasQualityDecision);
        } else {
            task.setStatus("FAILED");
            task.setStage("FAILED");
            task.setFlowStatus("FAILED");
            if (!StringUtils.hasText(task.getErrorMessage())) {
                task.setErrorMessage("远程检测服务返回失败状态");
            }
        }
        detectionTaskMapper.updateById(task);

        // 检测完成通知：如果任务是从聊天助手创建的，发送通知消息
        notifyDetectionCompleted(task);
    }

    private void notifyDetectionCompleted(DetectionTask task) {
        String sessionId = task.getSessionId();
        if (!StringUtils.hasText(sessionId)) return;

        try {
            String statusLabel;
            if ("COMPLETED".equals(task.getStatus())) {
                statusLabel = "已完成";
            } else if ("PARTIAL_FAILED".equals(task.getStatus())) {
                statusLabel = "部分失败";
            } else {
                statusLabel = "失败";
            }

            String msg = "检测任务「" + task.getTaskId() + "」" + statusLabel + "。\n\n"
                    + "任务信息：\n"
                    + "- 工作流UUID：`" + task.getWorkflowUuid() + "`\n"
                    + "- 图片总数：" + (task.getTotalImages() != null ? task.getTotalImages() : 0) + "\n"
                    + "- 成功：" + (task.getSuccessfulImages() != null ? task.getSuccessfulImages() : 0) + "\n"
                    + "- 失败：" + (task.getFailedImages() != null ? task.getFailedImages() : 0) + "\n\n"
                    + "你可以输入「查看任务 " + task.getTaskId() + "」查看详情。";

            detectionNotificationPort.notifyTaskCompleted(sessionId, msg);
            log.info("检测完成通知已发送: taskId={}, sessionId={}", task.getTaskId(), sessionId);
        } catch (Exception e) {
            log.error("发送检测完成通知失败: taskId={}, sessionId={}", task.getTaskId(), sessionId, e);
        }
    }

    @CacheEvict(cacheNames = {"detection-task", "dashboard"}, allEntries = true)
    public void failTask(String taskId, String errorMessage) {
        DetectionTask task = getTaskForSystem(taskId);
        task.setStatus("FAILED");
        task.setStage("FAILED");
        task.setErrorMessage(errorMessage);
        task.setFinishedAt(LocalDateTime.now());
        task.setUpdatedAt(LocalDateTime.now());
        detectionTaskMapper.updateById(task);
    }

    public List<String> readJsonList(String json) {
        if (!StringUtils.hasText(json)) {
            return Collections.emptyList();
        }
        try {
            return objectMapper.readValue(json, new TypeReference<List<String>>() {});
        } catch (JsonProcessingException ex) {
            log.warn("解析列表 JSON 失败: {}", json, ex);
            return Collections.emptyList();
        }
    }

    private List<DetectionTraceImage> buildTraceImages(List<String> objectKeys) {
        return objectKeys.stream()
                .map(key -> DetectionTraceImage.builder()
                        .imageName(extractFileName(key))
                        .objectKey(key)
                        .previewUrl(signUrl(key))
                        .build())
                .toList();
    }

    private List<DetectionTraceEvent> buildTraceTimeline(DetectionTask task) {
        List<DetectionTraceEvent> events = new ArrayList<>();
        addTraceEvent(events, "CREATED", "任务创建", task.getCreatedAt(), task.getCreatedBy(),
                "生成批次 " + safeText(task.getBatchNo()) + " 与工单 " + safeText(task.getWorkOrderNo()));
        addTraceEvent(events, "DISPATCHED", "开始检测", task.getStartedAt(), "检测服务",
                "模型版本 " + safeText(task.getModelVersion()) + " 开始推理");
        addTraceEvent(events, "FINISHED", "检测完成", task.getFinishedAt(), "检测服务",
                "成功 " + defaultInt(task.getSuccessfulImages()) + " 张，失败 " + defaultInt(task.getFailedImages()) + " 张");
        addTraceEvent(events, "ASSIGNED", "质检分派", task.getAssignedAt(), task.getAssignee(),
                "站点 " + safeText(task.getQualityStation()) + "，截止 " + safeText(formatDateTime(task.getDueAt())));
        addTraceEvent(events, "REVIEWED", "人工复核", task.getReviewedAt(), task.getReviewer(),
                "结论 " + safeText(task.getReviewConclusion()) + "，严重等级 " + safeText(task.getSeverityLevel()));
        addTraceEvent(events, "DISPOSED", "质检处置", task.getDisposedAt(), task.getDispositionOperator(),
                "动作 " + safeText(task.getDispositionAction()) + "，备注 " + safeText(task.getDispositionRemark()));
        addTraceEvent(events, "REWORK_COMPLETED", "返工回填", task.getReworkCompletedAt(), task.getReworkOperator(),
                "结果 " + safeText(task.getReworkResult()) + "，复检 " + (Boolean.TRUE.equals(task.getRecheckRequired()) ? "需要" : "不需要"));
        return events;
    }

    private void addTraceEvent(List<DetectionTraceEvent> events, String eventType, String eventName,
                               LocalDateTime occurredAt, String operator, String description) {
        if (occurredAt == null) {
            return;
        }
        events.add(DetectionTraceEvent.builder()
                .eventType(eventType)
                .eventName(eventName)
                .occurredAt(formatDateTime(occurredAt))
                .operator(StringUtils.hasText(operator) ? operator : "系统")
                .description(description)
                .build());
    }

    private java.util.Map<String, Object> buildReportCaptureSection(DetectionTask task) {
        java.util.Map<String, Object> capture = new LinkedHashMap<>();
        capture.put("captureDate", task.getCaptureDate());
        capture.put("region", task.getRegion());
        capture.put("collector", task.getCollector());
        capture.put("deviceName", task.getDeviceName());
        capture.put("imageFolderName", task.getImageFolderName());
        capture.put("sourceOssPrefix", task.getSourceOssPrefix());
        return capture;
    }

    private java.util.Map<String, Object> buildReportModelSection(DetectionTask task) {
        java.util.Map<String, Object> model = new LinkedHashMap<>();
        model.put("modelId", task.getModelId());
        model.put("modelVersion", task.getModelVersion());
        model.put("threshold", task.getThreshold());
        return model;
    }

    private java.util.Map<String, Object> buildReportInspectionSection(DetectionTask task) {
        java.util.Map<String, Object> inspection = new LinkedHashMap<>();
        inspection.put("totalImages", defaultInt(task.getTotalImages()));
        inspection.put("successfulImages", defaultInt(task.getSuccessfulImages()));
        inspection.put("failedImages", defaultInt(task.getFailedImages()));
        inspection.put("statistics", readJsonMap(task.getStatisticsJson()));
        inspection.put("defectCount", defaultInt(task.getDefectCount()));
        inspection.put("primaryDefectType", task.getPrimaryDefectType());
        inspection.put("maxDefectSeverity", task.getMaxDefectSeverity());
        inspection.put("resultOssPrefix", task.getResultOssPrefix());
        inspection.put("detectionStartedAt", formatDateTime(task.getStartedAt()));
        inspection.put("detectionFinishedAt", formatDateTime(task.getFinishedAt()));
        inspection.put("errorMessage", task.getErrorMessage());
        return inspection;
    }

    private java.util.Map<String, Object> buildReportReviewSection(DetectionTask task) {
        java.util.Map<String, Object> review = new LinkedHashMap<>();
        review.put("reviewStatus", task.getReviewStatus());
        review.put("reviewConclusion", task.getReviewConclusion());
        review.put("severityLevel", task.getSeverityLevel());
        review.put("confirmedDefectCount", defaultInt(task.getConfirmedDefectCount()));
        review.put("falsePositiveCount", defaultInt(task.getFalsePositiveCount()));
        review.put("reviewRemark", task.getReviewRemark());
        review.put("reviewer", task.getReviewer());
        review.put("reviewedAt", formatDateTime(task.getReviewedAt()));
        return review;
    }

    private java.util.Map<String, Object> buildReportAssignmentSection(DetectionTask task) {
        java.util.Map<String, Object> assignment = new LinkedHashMap<>();
        assignment.put("qualityStation", task.getQualityStation());
        assignment.put("assignee", task.getAssignee());
        assignment.put("assignmentRemark", task.getAssignmentRemark());
        assignment.put("assignedAt", formatDateTime(task.getAssignedAt()));
        assignment.put("dueAt", formatDateTime(task.getDueAt()));
        return assignment;
    }

    private java.util.Map<String, Object> buildReportDispositionSection(DetectionTask task) {
        java.util.Map<String, Object> disposition = new LinkedHashMap<>();
        disposition.put("dispositionStatus", task.getDispositionStatus());
        disposition.put("dispositionAction", task.getDispositionAction());
        disposition.put("dispositionRemark", task.getDispositionRemark());
        disposition.put("dispositionOperator", task.getDispositionOperator());
        disposition.put("disposedAt", formatDateTime(task.getDisposedAt()));
        disposition.put("recheckRequired", Boolean.TRUE.equals(task.getRecheckRequired()));
        return disposition;
    }

    private java.util.Map<String, Object> buildReportReworkSection(DetectionTask task) {
        java.util.Map<String, Object> rework = new LinkedHashMap<>();
        rework.put("reworkResult", task.getReworkResult());
        rework.put("reworkOperator", task.getReworkOperator());
        rework.put("reworkRemark", task.getReworkRemark());
        rework.put("reworkCompletedAt", formatDateTime(task.getReworkCompletedAt()));
        rework.put("recheckRequired", Boolean.TRUE.equals(task.getRecheckRequired()));
        return rework;
    }

    private java.util.Map<String, Object> buildReportEvidenceSection(DetectionTask task,
                                                                     List<DetectionTraceImage> originalImages,
                                                                     List<DetectionTraceImage> previewImages) {
        java.util.Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("resultJsonKey", task.getResultJsonOssKey());
        evidence.put("resultJsonUrl", signUrl(task.getResultJsonOssKey()));
        evidence.put("originalImages", originalImages);
        evidence.put("previewImages", previewImages);
        evidence.put("defectEvidence", readJsonMapList(task.getDefectEvidenceJson()));
        return evidence;
    }

    private java.util.Map<String, Object> buildBatchSummary(List<DetectionTask> tasks) {
        DetectionTask first = tasks.get(0);
        java.util.Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("taskCount", tasks.size());
        summary.put("captureDate", first.getCaptureDate());
        summary.put("region", first.getRegion());
        summary.put("collector", first.getCollector());
        summary.put("workOrders", distinctTexts(tasks.stream().map(DetectionTask::getWorkOrderNo).toList()));
        summary.put("devices", distinctTexts(tasks.stream().map(DetectionTask::getDeviceName).toList()));
        summary.put("models", distinctTexts(tasks.stream()
                .map(task -> task.getModelId() == null ? null : task.getModelId() + "/" + safeText(task.getModelVersion()))
                .toList()));
        summary.put("sourcePrefixes", distinctTexts(tasks.stream().map(DetectionTask::getSourceOssPrefix).toList()));
        summary.put("resultPrefixes", distinctTexts(tasks.stream().map(DetectionTask::getResultOssPrefix).toList()));
        return summary;
    }

    private java.util.Map<String, Object> buildWorkOrderSummary(List<DetectionTask> tasks) {
        DetectionTask first = tasks.get(0);
        java.util.Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("taskCount", tasks.size());
        summary.put("captureDate", first.getCaptureDate());
        summary.put("regions", distinctTexts(tasks.stream().map(DetectionTask::getRegion).toList()));
        summary.put("collectors", distinctTexts(tasks.stream().map(DetectionTask::getCollector).toList()));
        summary.put("batchNos", distinctTexts(tasks.stream().map(DetectionTask::getBatchNo).toList()));
        summary.put("devices", distinctTexts(tasks.stream().map(DetectionTask::getDeviceName).toList()));
        summary.put("models", distinctTexts(tasks.stream()
                .map(task -> task.getModelId() == null ? null : task.getModelId() + "/" + safeText(task.getModelVersion()))
                .toList()));
        summary.put("sourcePrefixes", distinctTexts(tasks.stream().map(DetectionTask::getSourceOssPrefix).toList()));
        summary.put("resultPrefixes", distinctTexts(tasks.stream().map(DetectionTask::getResultOssPrefix).toList()));
        return summary;
    }

    private java.util.Map<String, Object> buildBatchInspection(List<DetectionTask> tasks) {
        int totalImages = tasks.stream().mapToInt(task -> defaultInt(task.getTotalImages())).sum();
        int processedImages = tasks.stream().mapToInt(task -> defaultInt(task.getProcessedImages())).sum();
        int successfulImages = tasks.stream().mapToInt(task -> defaultInt(task.getSuccessfulImages())).sum();
        int failedImages = tasks.stream().mapToInt(task -> defaultInt(task.getFailedImages())).sum();
        int defectCount = tasks.stream().mapToInt(task -> defaultInt(task.getDefectCount())).sum();
        int confirmedDefects = tasks.stream().mapToInt(task -> defaultInt(task.getConfirmedDefectCount())).sum();
        int falsePositives = tasks.stream().mapToInt(task -> defaultInt(task.getFalsePositiveCount())).sum();

        java.util.Map<String, Object> inspection = new LinkedHashMap<>();
        inspection.put("totalImages", totalImages);
        inspection.put("processedImages", processedImages);
        inspection.put("successfulImages", successfulImages);
        inspection.put("failedImages", failedImages);
        inspection.put("defectCount", defectCount);
        inspection.put("confirmedDefectCount", confirmedDefects);
        inspection.put("falsePositiveCount", falsePositives);
        inspection.put("defectRate", totalImages == 0 ? 0.0 : defectCount * 1.0 / totalImages);
        inspection.put("successRate", totalImages == 0 ? 0.0 : successfulImages * 1.0 / totalImages);
        return inspection;
    }

    private java.util.Map<String, Object> buildBatchQuality(List<DetectionTask> tasks) {
        long pendingReview = tasks.stream().filter(task -> "PENDING".equals(task.getReviewStatus())).count();
        long reviewed = tasks.stream().filter(task -> "REVIEWED".equals(task.getReviewStatus())).count();
        long disposed = tasks.stream().filter(task -> "DISPOSED".equals(task.getDispositionStatus())).count();
        long reworkRequired = tasks.stream().filter(task -> "REWORK_REQUIRED".equals(task.getFlowStatus())).count();
        long recheckRequired = tasks.stream()
                .filter(task -> "RECHECK_REQUIRED".equals(task.getFlowStatus()) || Boolean.TRUE.equals(task.getRecheckRequired()))
                .count();
        long closed = tasks.stream().filter(this::isFinalQualityClosed).count();

        java.util.Map<String, Object> quality = new LinkedHashMap<>();
        quality.put("pendingReview", pendingReview);
        quality.put("reviewed", reviewed);
        quality.put("disposed", disposed);
        quality.put("reworkRequired", reworkRequired);
        quality.put("recheckRequired", recheckRequired);
        quality.put("closed", closed);
        quality.put("reviewCompletionRate", tasks.isEmpty() ? 0.0 : reviewed * 1.0 / tasks.size());
        quality.put("closureRate", tasks.isEmpty() ? 0.0 : closed * 1.0 / tasks.size());
        return quality;
    }

    private java.util.Map<String, Object> buildBatchDistribution(List<DetectionTask> tasks) {
        java.util.Map<String, Object> distribution = new LinkedHashMap<>();
        distribution.put("status", countByText(tasks.stream().map(DetectionTask::getStatus).toList()));
        distribution.put("flowStatus", countByText(tasks.stream().map(DetectionTask::getFlowStatus).toList()));
        distribution.put("defectType", countByText(tasks.stream().map(DetectionTask::getPrimaryDefectType).toList()));
        distribution.put("severity", countByText(tasks.stream().map(DetectionTask::getMaxDefectSeverity).toList()));
        distribution.put("device", countByText(tasks.stream().map(DetectionTask::getDeviceName).toList()));
        distribution.put("model", countByText(tasks.stream()
                .map(task -> task.getModelId() == null ? null : String.valueOf(task.getModelId()))
                .toList()));
        return distribution;
    }

    private java.util.Map<String, Object> buildBatchTimeRange(List<DetectionTask> tasks) {
        java.util.Map<String, Object> timeRange = new LinkedHashMap<>();
        timeRange.put("createdFrom", formatDateTime(minTime(tasks.stream().map(DetectionTask::getCreatedAt).toList())));
        timeRange.put("createdTo", formatDateTime(maxTime(tasks.stream().map(DetectionTask::getCreatedAt).toList())));
        timeRange.put("startedFrom", formatDateTime(minTime(tasks.stream().map(DetectionTask::getStartedAt).toList())));
        timeRange.put("finishedTo", formatDateTime(maxTime(tasks.stream().map(DetectionTask::getFinishedAt).toList())));
        timeRange.put("lastUpdatedAt", formatDateTime(maxTime(tasks.stream().map(DetectionTask::getUpdatedAt).toList())));
        return timeRange;
    }

    private String safeText(String value) {
        return StringUtils.hasText(value) ? value : "--";
    }

    public String getBucketName() {
        return ossStorageService.getBucketName();
    }

    private DetectionTaskProgressResponse buildProgressResponse(DetectionTask task, String messageOverride) {
        LocalDateTime updatedAt = task.getUpdatedAt() != null ? task.getUpdatedAt() : task.getCreatedAt();
        String folderName = buildFolderLabel(task);
        return DetectionTaskProgressResponse.builder()
                .taskId(task.getTaskId())
                .workflowUuid(task.getWorkflowUuid())
                .status(task.getStatus())
                .stage(task.getStage())
                .batchNo(task.getBatchNo())
                .workOrderNo(task.getWorkOrderNo())
                .flowStatus(task.getFlowStatus())
                .qualityStation(task.getQualityStation())
                .assignee(task.getAssignee())
                .assignmentRemark(task.getAssignmentRemark())
                .assignedAt(formatDateTime(task.getAssignedAt()))
                .dueAt(formatDateTime(task.getDueAt()))
                .progressPercent(resolveProgressPercent(task))
                .totalImages(defaultInt(task.getTotalImages()))
                .processedImages(defaultInt(task.getProcessedImages()))
                .successfulImages(defaultInt(task.getSuccessfulImages()))
                .failedImages(defaultInt(task.getFailedImages()))
                .defectCount(defaultInt(task.getDefectCount()))
                .primaryDefectType(task.getPrimaryDefectType())
                .maxDefectSeverity(task.getMaxDefectSeverity())
                .message(StringUtils.hasText(messageOverride) ? messageOverride : resolveProgressMessage(task))
                .createdAt(task.getCreatedAt() != null ? task.getCreatedAt().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")) : null)
                .updatedAt(updatedAt == null ? null : updatedAt.format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")))
                .finishedAt(task.getFinishedAt() != null ? task.getFinishedAt().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")) : null)
                .folderName(folderName)
                .errorMessage(task.getErrorMessage())
                .reviewStatus(task.getReviewStatus())
                .reviewConclusion(task.getReviewConclusion())
                .severityLevel(task.getSeverityLevel())
                .confirmedDefectCount(defaultInt(task.getConfirmedDefectCount()))
                .falsePositiveCount(defaultInt(task.getFalsePositiveCount()))
                .reviewRemark(task.getReviewRemark())
                .reviewer(task.getReviewer())
                .reviewedAt(formatDateTime(task.getReviewedAt()))
                .dispositionStatus(task.getDispositionStatus())
                .dispositionAction(task.getDispositionAction())
                .dispositionRemark(task.getDispositionRemark())
                .dispositionOperator(task.getDispositionOperator())
                .disposedAt(formatDateTime(task.getDisposedAt()))
                .recheckRequired(Boolean.TRUE.equals(task.getRecheckRequired()))
                .reworkResult(task.getReworkResult())
                .reworkOperator(task.getReworkOperator())
                .reworkRemark(task.getReworkRemark())
                .reworkCompletedAt(formatDateTime(task.getReworkCompletedAt()))
                .captureDate(task.getCaptureDate())
                .region(task.getRegion())
                .collector(task.getCollector())
                .deviceName(task.getDeviceName())
                .imageFolderName(task.getImageFolderName())
                .sourceOssPrefix(task.getSourceOssPrefix())
                .build();
    }

    private String buildFolderLabel(DetectionTask task) {
        String region = StringUtils.hasText(task.getRegion()) ? task.getRegion() : "未知";
        String folder = StringUtils.hasText(task.getImageFolderName()) ? task.getImageFolderName() : "未命名";
        return region + " / " + folder;
    }

    private int resolveProgressPercent(DetectionTask task) {
        if ("COMPLETED".equals(task.getStatus()) || "PARTIAL_FAILED".equals(task.getStatus())) {
            return 100;
        }
        if ("FAILED".equals(task.getStatus())) {
            return 100;
        }
        return switch (task.getStatus() == null ? "" : task.getStatus()) {
            case "UPLOADING" -> 25;
            case "UPLOADED" -> 34;
            case "QUEUED" -> 40;
            case "DETECTING" -> 65;
            case "UPLOADING_RESULT" -> 90;
            default -> 0;
        };
    }

    private String resolveProgressMessage(DetectionTask task) {
        if (StringUtils.hasText(task.getErrorMessage())) {
            return task.getErrorMessage();
        }
        return switch (task.getStatus() == null ? "" : task.getStatus()) {
            case "UPLOADING" -> "正在上传图片到 OSS，请等待上传完成";
            case "UPLOADED" -> "已交给模型处理";
            case "QUEUED" -> "已交给模型处理，等待检测服务调度";
            case "DETECTING" -> "模型正在检测";
            case "UPLOADING_RESULT" -> "模型正在检测，即将完成";
            case "COMPLETED" -> "检测完成";
            case "PARTIAL_FAILED" -> "检测完成（部分失败）";
            case "FAILED" -> "检测失败";
            default -> "任务已创建";
        };
    }

    private DetectionTask getTask(String taskId) {
        DetectionTask task = getTaskForSystem(taskId);
        accessPolicy.assertCanAccess(task, SecurityContextHolder.getContext().getAuthentication());
        return task;
    }

    private DetectionTask getTaskForSystem(String taskId) {
        DetectionTask task = detectionTaskMapper.selectOne(new LambdaQueryWrapper<DetectionTask>()
                .eq(DetectionTask::getTaskId, taskId)
                .last("limit 1"));
        if (task == null) {
            throw new BusinessException("检测任务不存在");
        }
        return task;
    }

    private DetectionTask getTaskForSystemLocked(String taskId) {
        DetectionTask task = detectionTaskMapper.selectOne(new LambdaQueryWrapper<DetectionTask>()
                .eq(DetectionTask::getTaskId, taskId)
                .last("limit 1 for update"));
        if (task == null) {
            throw new BusinessException("检测任务不存在");
        }
        return task;
    }

    private void applyOwnerFilter(LambdaQueryWrapper<DetectionTask> wrapper) {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        accessPolicy.assertAuthenticated(authentication);
    }

    private ModelInfo resolveModelInfo(Integer modelId) {
        if (modelId != null) {
            ModelInfo modelInfo = modelInfoMapper.selectByModelId(modelId);
            if (modelInfo == null) {
                throw new BusinessException("所选模型不存在");
            }
            return modelInfo;
        }
        List<ModelInfo> allModels = modelService.getAllModels();
        if (allModels == null || allModels.isEmpty()) {
            return null;
        }
        return allModels.stream()
                .filter(model -> Boolean.TRUE.equals(model.getIsDefault()))
                .findFirst()
                .orElseGet(() -> allModels.stream()
                        .filter(model -> "PUBLISHED".equals(model.getStatus()))
                        .findFirst()
                        .orElse(allModels.get(0)));
    }

    private String buildTaskId() {
        return "det_" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss"))
                + "_" + UUID.randomUUID().toString().replace("-", "").substring(0, 8);
    }

    private String buildWorkOrderNo() {
        return "WO-" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMddHHmmss"))
                + "-" + UUID.randomUUID().toString().replace("-", "").substring(0, 6).toUpperCase(Locale.ROOT);
    }

    private String buildBatchNo(DetectionCaptureInfo captureInfo) {
        return String.join("_",
                captureInfo.getCaptureDate(),
                captureInfo.getRegion(),
                captureInfo.getDeviceName(),
                captureInfo.getImageFolderName()
        );
    }

    private DetectionCaptureInfo normalizeCaptureInfo(DetectionCaptureInfo source) {
        DetectionCaptureInfo target = new DetectionCaptureInfo();
        target.setCaptureDate(normalizePathSegment(source == null ? null : source.getCaptureDate(), "unknown-date"));
        target.setRegion(normalizePathSegment(source == null ? null : source.getRegion(), "unknown-region"));
        target.setCollector(normalizePathSegment(source == null ? null : source.getCollector(), "unknown-collector"));
        target.setDeviceName(normalizePathSegment(source == null ? null : source.getDeviceName(), "unknown-device"));
        target.setImageFolderName(normalizePathSegment(source == null ? null : source.getImageFolderName(), "unknown-folder"));
        return target;
    }

    private String normalizeFlowStatus(String targetFlowStatus) {
        if (!StringUtils.hasText(targetFlowStatus)) {
            throw new BusinessException("目标流转状态不能为空");
        }
        return targetFlowStatus.trim().toUpperCase(Locale.ROOT);
    }

    private String normalizeReviewValue(String value, String fallback) {
        return StringUtils.hasText(value) ? value.trim().toUpperCase(Locale.ROOT) : fallback;
    }

    private String normalizeReviewConclusion(String value) {
        String normalized = normalizeReviewValue(value, "CONFIRMED_DEFECT");
        return switch (normalized) {
            case "PASS" -> "NORMAL_RELEASE";
            case "DEFECT", "REJECT" -> "CONFIRMED_DEFECT";
            case "RECHECK" -> "NEEDS_RECHECK";
            default -> normalized;
        };
    }

    private String normalizeSeverityLevel(String value) {
        String normalized = normalizeReviewValue(value, "MINOR");
        return switch (normalized) {
            case "LOW" -> "MINOR";
            case "MEDIUM" -> "MAJOR";
            case "HIGH" -> "CRITICAL";
            default -> normalized;
        };
    }

    private void validateReviewPayload(String reviewConclusion, String severityLevel,
                                       int confirmedDefectCount, int falsePositiveCount) {
        if (!SUPPORTED_REVIEW_CONCLUSIONS.contains(reviewConclusion)) {
            throw new BusinessException("不支持的复核结论: " + reviewConclusion);
        }
        if (!SUPPORTED_SEVERITY_LEVELS.contains(severityLevel)) {
            throw new BusinessException("不支持的严重等级: " + severityLevel);
        }
        if (confirmedDefectCount < 0 || falsePositiveCount < 0) {
            throw new BusinessException("复核数量不能为负数");
        }
    }

    private String normalizeDispositionAction(String value) {
        if (!StringUtils.hasText(value)) {
            throw new BusinessException("处置动作不能为空");
        }
        String action = value.trim().toUpperCase(Locale.ROOT);
        if (!SUPPORTED_DISPOSITION_ACTIONS.contains(action)) {
            throw new BusinessException("不支持的处置动作: " + action);
        }
        return action;
    }

    private void validateDispositionReady(DetectionTask task) {
        if (!"COMPLETED".equals(task.getStatus()) && !"PARTIAL_FAILED".equals(task.getStatus())) {
            throw new BusinessException("只有已完成检测任务才能处置");
        }
        if (!"REVIEWED".equals(task.getReviewStatus())) {
            throw new BusinessException("检测任务需先完成人工复核再处置");
        }
        if (isQualityDisposed(task)) {
            throw new BusinessException("任务已完成质检处置，不能重复处置");
        }
    }

    private void validateDispositionAction(DetectionTask task, String action) {
        if ("RELEASE".equals(action)
                && !"NORMAL_RELEASE".equals(task.getReviewConclusion())
                && !"FALSE_POSITIVE".equals(task.getReviewConclusion())) {
            throw new BusinessException("存在确认缺陷或待复检结论的任务不能直接放行");
        }
    }

    private void validateRetryable(DetectionTask task) {
        boolean retryable = "FAILED".equals(task.getStatus())
                || "FAILED".equals(task.getFlowStatus())
                || "RECHECK_REQUIRED".equals(task.getFlowStatus())
                || "REWORK_REQUIRED".equals(task.getFlowStatus());
        if (!retryable) {
            throw new BusinessException("当前任务状态不支持重新检测");
        }
        if (readJsonList(task.getOriginalImageKeysJson()).isEmpty()) {
            throw new BusinessException("任务缺少原图证据，无法重新检测");
        }
    }

    private String resolveDispositionFlowStatus(String action, Boolean recheckRequired) {
        if (Boolean.TRUE.equals(recheckRequired)) {
            return "RECHECK_REQUIRED";
        }
        return switch (action) {
            case "RELEASE" -> "RELEASED";
            case "REWORK" -> "REWORK_REQUIRED";
            case "RECHECK" -> "RECHECK_REQUIRED";
            case "HOLD" -> "HOLD";
            case "SCRAP" -> "SCRAPPED";
            default -> "DISPOSED";
        };
    }

    private void validateFlowTransition(String currentFlowStatus, String targetFlowStatus) {
        String current = StringUtils.hasText(currentFlowStatus) ? currentFlowStatus : "PENDING_REVIEW";
        if (DISPOSITION_FLOW_STATUSES.contains(targetFlowStatus)) {
            throw new BusinessException("处置类状态请通过质检处置接口流转");
        }
        Map<String, List<String>> allowedTransitions = Map.of(
                "PENDING_REVIEW", List.of("REVIEWING", "CONFIRMED"),
                "REVIEWING", List.of("CONFIRMED", "PENDING_REVIEW"),
                "CONFIRMED", List.of("RELEASED", "REWORK_REQUIRED", "RECHECK_REQUIRED", "HOLD", "SCRAPPED", "ARCHIVED"),
                "REWORK_REQUIRED", List.of("RECHECK_REQUIRED", "ARCHIVED"),
                "RECHECK_REQUIRED", List.of("PENDING_REVIEW", "ARCHIVED"),
                "HOLD", List.of("REWORK_REQUIRED", "RECHECK_REQUIRED", "RELEASED", "SCRAPPED", "ARCHIVED"),
                "RELEASED", List.of("ARCHIVED"),
                "SCRAPPED", List.of("ARCHIVED"),
                "ARCHIVED", List.of(),
                "FAILED", List.of("PENDING_REVIEW")
        );
        List<String> allowedTargets = allowedTransitions.getOrDefault(current, Collections.emptyList());
        if (!allowedTargets.contains(targetFlowStatus)) {
            throw new BusinessException("不允许从 " + current + " 流转到 " + targetFlowStatus);
        }
    }

    private boolean hasQualityDecision(DetectionTask task) {
        return "REVIEWED".equals(task.getReviewStatus()) || isQualityDisposed(task);
    }

    private boolean isQualityDisposed(DetectionTask task) {
        return isFinalQualityClosed(task)
                || ("DISPOSED".equals(task.getDispositionStatus()) && !isReopenedQualityFlow(task));
    }

    private boolean isFinalQualityClosed(DetectionTask task) {
        String flowStatus = task.getFlowStatus();
        return "RELEASED".equals(flowStatus) || "SCRAPPED".equals(flowStatus) || "ARCHIVED".equals(flowStatus);
    }

    private boolean isReopenedQualityFlow(DetectionTask task) {
        String flowStatus = task.getFlowStatus();
        return "PENDING_REVIEW".equals(flowStatus) || "RECHECK_REQUIRED".equals(flowStatus);
    }

    private void resetQualityWorkflowIfUnreviewed(DetectionTask task, boolean hasQualityDecision) {
        if (hasQualityDecision) {
            return;
        }
        task.setFlowStatus("PENDING_REVIEW");
        task.setReviewStatus("PENDING");
        task.setDispositionStatus(null);
    }

    private void applyDefectEvidence(DetectionTask task, DetectionTaskFinishedEvent event) {
        List<Map<String, Object>> defectEvidence = resolveDefectEvidence(event);
        task.setDefectEvidenceJson(writeJson(defectEvidence));
        task.setDefectCount(defectEvidence.size());
        task.setPrimaryDefectType(resolvePrimaryDefectType(defectEvidence));
        task.setMaxDefectSeverity(resolveMaxDefectSeverity(defectEvidence));
    }

    private List<Map<String, Object>> resolveDefectEvidence(DetectionTaskFinishedEvent event) {
        if (event.getDefectEvidence() != null) {
            return normalizeDefectEvidence(event.getDefectEvidence());
        }
        Object fromStatistics = event.getStatistics() == null ? null : event.getStatistics().get("defectEvidence");
        if (fromStatistics instanceof List<?> list) {
            List<Map<String, Object>> defects = new ArrayList<>();
            for (Object item : list) {
                if (item instanceof Map<?, ?> map) {
                    defects.add(toStringKeyMap(map));
                }
            }
            return normalizeDefectEvidence(defects);
        }
        return Collections.emptyList();
    }

    private List<Map<String, Object>> normalizeDefectEvidence(List<Map<String, Object>> defectEvidence) {
        if (defectEvidence == null || defectEvidence.isEmpty()) {
            return Collections.emptyList();
        }
        return defectEvidence.stream()
                .map(this::normalizeDefectItem)
                .filter(item -> StringUtils.hasText(asString(item.get("defectType"))))
                .toList();
    }

    private Map<String, Object> normalizeDefectItem(Map<String, Object> source) {
        Map<String, Object> target = new LinkedHashMap<>();
        target.put("imageName", asString(source.get("imageName")));
        target.put("sourceKey", asString(source.get("sourceKey")));
        target.put("previewKey", asString(source.get("previewKey")));
        target.put("defectType", normalizeDefectType(source));
        target.put("confidence", source.get("confidence"));
        target.put("area", source.get("area"));
        target.put("positionRegion", normalizePositionRegion(source));
        target.put("severityLevel", normalizeEvidenceSeverity(source));
        Object bbox = source.get("bbox");
        if (bbox instanceof Map<?, ?> map) {
            target.put("bbox", toStringKeyMap(map));
        }
        return target;
    }

    private String normalizeDefectType(Map<String, Object> source) {
        String value = asString(source.get("defectType"));
        if (!StringUtils.hasText(value)) {
            value = asString(source.get("label"));
        }
        if (!StringUtils.hasText(value)) {
            value = asString(source.get("category"));
        }
        return value;
    }

    private String normalizePositionRegion(Map<String, Object> source) {
        String value = asString(source.get("positionRegion"));
        if (!StringUtils.hasText(value)) {
            value = asString(source.get("region"));
        }
        return StringUtils.hasText(value) ? value.toUpperCase(Locale.ROOT) : "UNKNOWN";
    }

    private String normalizeEvidenceSeverity(Map<String, Object> source) {
        String value = asString(source.get("severityLevel"));
        if (!StringUtils.hasText(value)) {
            value = asString(source.get("severity"));
        }
        return StringUtils.hasText(value) ? value.toUpperCase(Locale.ROOT) : "MINOR";
    }

    private String resolvePrimaryDefectType(List<Map<String, Object>> defectEvidence) {
        if (defectEvidence.isEmpty()) {
            return null;
        }
        Map<String, Long> counts = defectEvidence.stream()
                .map(item -> asString(item.get("defectType")))
                .filter(StringUtils::hasText)
                .collect(Collectors.groupingBy(type -> type, LinkedHashMap::new, Collectors.counting()));
        return counts.entrySet().stream()
                .max(Map.Entry.comparingByValue())
                .map(Map.Entry::getKey)
                .orElse(null);
    }

    private String resolveMaxDefectSeverity(List<Map<String, Object>> defectEvidence) {
        return defectEvidence.stream()
                .map(item -> asString(item.get("severityLevel")))
                .filter(StringUtils::hasText)
                .max((left, right) -> Integer.compare(severityRank(left), severityRank(right)))
                .orElse(null);
    }

    private int severityRank(String severity) {
        return switch (severity.toUpperCase(Locale.ROOT)) {
            case "CRITICAL" -> 3;
            case "MAJOR" -> 2;
            case "MINOR" -> 1;
            default -> 0;
        };
    }

    private String normalizeQualityQueue(String queue) {
        if (!StringUtils.hasText(queue)) {
            throw new BusinessException("质检队列不能为空");
        }
        String normalizedQueue = queue.trim().toUpperCase(Locale.ROOT);
        Set<String> supportedQueues = Set.of(
                "PENDING_REVIEW",
                "PENDING_DISPOSITION",
                "RECHECK_REQUIRED",
                "REWORK_REQUIRED",
                "HOLD",
                "FAILED",
                "ALL_ACTIONABLE"
        );
        if (!supportedQueues.contains(normalizedQueue)) {
            throw new BusinessException("不支持的质检队列: " + normalizedQueue);
        }
        return normalizedQueue;
    }

    private void applyQualityQueueFilter(LambdaQueryWrapper<DetectionTask> wrapper, String queue) {
        switch (queue) {
            case "PENDING_REVIEW" -> wrapper
                    .in(DetectionTask::getStatus, List.of("COMPLETED", "PARTIAL_FAILED"))
                    .eq(DetectionTask::getReviewStatus, "PENDING");
            case "PENDING_DISPOSITION" -> wrapper
                    .eq(DetectionTask::getReviewStatus, "REVIEWED")
                    .and(w -> w.isNull(DetectionTask::getDispositionStatus)
                            .or()
                            .eq(DetectionTask::getDispositionStatus, "PENDING"));
            case "RECHECK_REQUIRED" -> wrapper
                    .and(w -> w.eq(DetectionTask::getFlowStatus, "RECHECK_REQUIRED")
                            .or()
                            .eq(DetectionTask::getRecheckRequired, true));
            case "REWORK_REQUIRED" -> wrapper.eq(DetectionTask::getFlowStatus, "REWORK_REQUIRED");
            case "HOLD" -> wrapper.eq(DetectionTask::getFlowStatus, "HOLD");
            case "FAILED" -> wrapper
                    .and(w -> w.eq(DetectionTask::getStatus, "FAILED")
                            .or()
                            .eq(DetectionTask::getFlowStatus, "FAILED"));
            case "ALL_ACTIONABLE" -> wrapper.and(w -> w
                    .in(DetectionTask::getFlowStatus, List.of("PENDING_REVIEW", "RECHECK_REQUIRED", "REWORK_REQUIRED", "HOLD", "FAILED"))
                    .or()
                    .eq(DetectionTask::getReviewStatus, "PENDING")
                    .or()
                    .eq(DetectionTask::getStatus, "FAILED")
                    .or()
                    .and(inner -> inner.eq(DetectionTask::getReviewStatus, "REVIEWED")
                            .and(disposition -> disposition.isNull(DetectionTask::getDispositionStatus)
                                    .or()
                                    .eq(DetectionTask::getDispositionStatus, "PENDING"))));
            default -> throw new BusinessException("不支持的质检队列: " + queue);
        }
    }

    private String buildUploadPrefix(DetectionCaptureInfo captureInfo) {
        return String.join("/",
                ossStorageService.normalizeBasePrefix(),
                captureInfo.getCaptureDate(),
                captureInfo.getRegion(),
                captureInfo.getCollector(),
                captureInfo.getDeviceName(),
                captureInfo.getImageFolderName(),
                "Original"
        ) + "/";
    }

    private void validateUploadFiles(List<DetectionUploadFileRequest> files) {
        if (files == null || files.isEmpty()) {
            throw new BusinessException("请至少选择一张图片");
        }
        if (files.size() > maxImagesPerBatch) {
            throw new BusinessException("单次最多上传 " + maxImagesPerBatch + " 张图片");
        }
        for (DetectionUploadFileRequest file : files) {
            if (file == null || !StringUtils.hasText(file.getFileName())) {
                throw new BusinessException("文件名不能为空");
            }
            String extension = extractExtension(file.getFileName());
            if (!SUPPORTED_UPLOAD_IMAGE_EXTENSIONS.contains(extension)) {
                throw new BusinessException("仅支持 JPG、PNG、BMP 图片");
            }
            String contentType = file.getContentType();
            if (StringUtils.hasText(contentType)
                    && !SUPPORTED_UPLOAD_IMAGE_CONTENT_TYPES.contains(contentType.toLowerCase(Locale.ROOT))) {
                throw new BusinessException("图片 Content-Type 不受支持: " + contentType);
            }
            Long fileSize = file.getFileSize();
            if (fileSize != null && fileSize > maxImageBytes) {
                throw new BusinessException("图片文件不能超过 " + formatBytes(maxImageBytes));
            }
        }
    }

    private List<String> validateUploadedKeys(DetectionTask task, List<DetectionUploadedFileItem> uploadedFiles) {
        String sourcePrefix = task.getSourceOssPrefix();
        List<String> uploadedKeys = uploadedFiles.stream()
                .map(item -> item == null ? null : item.getObjectKey())
                .filter(StringUtils::hasText)
                .peek(key -> {
                    if (StringUtils.hasText(sourcePrefix) && !key.startsWith(sourcePrefix)) {
                        throw new BusinessException("上传文件对象 Key 不属于当前任务");
                    }
                    String extension = extractExtension(key);
                    if (!SUPPORTED_UPLOAD_IMAGE_EXTENSIONS.contains(extension)) {
                        throw new BusinessException("仅支持 JPG、PNG、BMP 图片");
                    }
                })
                .toList();
        if (uploadedKeys.isEmpty()) {
            throw new BusinessException("上传文件对象 Key 不能为空");
        }
        return uploadedKeys;
    }

    private String extractExtension(String fileName) {
        if (!StringUtils.hasText(fileName)) {
            return "";
        }
        int queryIndex = fileName.indexOf('?');
        String cleanName = queryIndex >= 0 ? fileName.substring(0, queryIndex) : fileName;
        int dotIndex = cleanName.lastIndexOf('.');
        return dotIndex >= 0 ? cleanName.substring(dotIndex).toLowerCase(Locale.ROOT) : "";
    }

    private String formatBytes(long bytes) {
        if (bytes >= 1024L * 1024L) {
            return (bytes / 1024L / 1024L) + "MB";
        }
        if (bytes >= 1024L) {
            return (bytes / 1024L) + "KB";
        }
        return bytes + "B";
    }

    private String buildObjectName(DetectionUploadFileRequest file) {
        List<String> segments = extractRelativeObjectSegments(file);
        return String.join("/", segments);
    }

    private List<String> extractRelativeObjectSegments(DetectionUploadFileRequest file) {
        String rawPath = StringUtils.hasText(file.getRelativePath()) ? file.getRelativePath() : file.getFileName();
        rawPath = Normalizer.normalize(rawPath, Normalizer.Form.NFKC).replace("\\", "/");

        List<String> rawSegments = new ArrayList<>();
        for (String segment : rawPath.split("/")) {
            if (StringUtils.hasText(segment)) {
                rawSegments.add(segment.trim());
            }
        }

        List<String> relativeSegments = rawSegments.size() > 5
                ? new ArrayList<>(rawSegments.subList(5, rawSegments.size()))
                : new ArrayList<>();

        String normalizedFileName = normalizePathSegment(file.getFileName(), "image.jpg");
        if (relativeSegments.isEmpty()) {
            relativeSegments.add(normalizedFileName);
        } else {
            relativeSegments.set(relativeSegments.size() - 1, normalizedFileName);
        }

        List<String> sanitizedSegments = new ArrayList<>();
        for (String segment : relativeSegments) {
            sanitizedSegments.add(normalizePathSegment(segment, "unknown"));
        }

        if (sanitizedSegments.isEmpty()) {
            sanitizedSegments.add("image.jpg");
        }
        return sanitizedSegments;
    }

    private String normalizePathSegment(String input, String fallback) {
        String value = StringUtils.hasText(input) ? input.trim() : fallback;
        value = Normalizer.normalize(value, Normalizer.Form.NFKC);
        value = value.replace("\\", "_").replace("/", "_");
        value = value.replaceAll("[\\r\\n\\t]+", "_");
        value = value.replaceAll("[<>:\"|?*]+", "_");
        value = value.replaceAll("^\\.+", "");
        value = value.replaceAll("\\s{2,}", " ");
        if (!StringUtils.hasText(value)) {
            return fallback;
        }
        return value;
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException ex) {
            throw new BusinessException("序列化任务数据失败: " + ex.getMessage());
        }
    }

    private Map<String, Object> readJsonMap(String json) {
        if (!StringUtils.hasText(json)) {
            return Collections.emptyMap();
        }
        try {
            return objectMapper.readValue(json, new TypeReference<Map<String, Object>>() {});
        } catch (JsonProcessingException ex) {
            log.warn("解析统计 JSON 失败: {}", json, ex);
            return Collections.emptyMap();
        }
    }

    private List<Map<String, Object>> readJsonMapList(String json) {
        if (!StringUtils.hasText(json)) {
            return Collections.emptyList();
        }
        try {
            return objectMapper.readValue(json, new TypeReference<List<Map<String, Object>>>() {});
        } catch (JsonProcessingException ex) {
            log.warn("解析缺陷证据 JSON 失败: {}", json, ex);
            return Collections.emptyList();
        }
    }

    private Map<String, Object> toStringKeyMap(Map<?, ?> source) {
        Map<String, Object> target = new LinkedHashMap<>();
        source.forEach((key, value) -> target.put(String.valueOf(key), value));
        return target;
    }

    private List<String> distinctTexts(List<String> values) {
        if (values == null || values.isEmpty()) {
            return Collections.emptyList();
        }
        return values.stream()
                .filter(StringUtils::hasText)
                .distinct()
                .toList();
    }

    private Map<String, Long> countByText(List<String> values) {
        if (values == null || values.isEmpty()) {
            return Collections.emptyMap();
        }
        return values.stream()
                .filter(StringUtils::hasText)
                .collect(Collectors.groupingBy(value -> value, LinkedHashMap::new, Collectors.counting()));
    }

    private LocalDateTime minTime(List<LocalDateTime> values) {
        if (values == null || values.isEmpty()) {
            return null;
        }
        return values.stream()
                .filter(java.util.Objects::nonNull)
                .min(LocalDateTime::compareTo)
                .orElse(null);
    }

    private LocalDateTime maxTime(List<LocalDateTime> values) {
        if (values == null || values.isEmpty()) {
            return null;
        }
        return values.stream()
                .filter(java.util.Objects::nonNull)
                .max(LocalDateTime::compareTo)
                .orElse(null);
    }

    private String asString(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    private String signUrl(String objectKey) {
        if (!StringUtils.hasText(objectKey) || !ossStorageService.isConfigured()) {
            return null;
        }
        return "/api/oss/preview?key=" + URLEncoder.encode(objectKey, StandardCharsets.UTF_8);
    }

    private String extractFileName(String objectKey) {
        if (!StringUtils.hasText(objectKey)) {
            return "";
        }
        int lastSlash = objectKey.lastIndexOf('/');
        return lastSlash >= 0 ? objectKey.substring(lastSlash + 1) : objectKey;
    }

    private String formatDateTime(LocalDateTime value) {
        if (value == null) {
            return null;
        }
        return value.format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"));
    }

    private DetectionTaskEventCaptureInfo toEventCaptureInfo(DetectionTask task) {
        return DetectionTaskEventCaptureInfo.builder()
                .captureDate(task.getCaptureDate())
                .region(task.getRegion())
                .collector(task.getCollector())
                .deviceName(task.getDeviceName())
                .imageFolderName(task.getImageFolderName())
                .build();
    }

    private LocalDateTime parseFinishedAt(String finishedAt) {
        return parseDateTime(finishedAt, LocalDateTime.now());
    }

    private LocalDateTime parseDateTime(String value, LocalDateTime fallback) {
        if (!StringUtils.hasText(value)) {
            return fallback;
        }
        try {
            return OffsetDateTime.parse(value).toLocalDateTime();
        } catch (Exception ex) {
            log.warn("解析 Kafka 时间失败: {}", value, ex);
            return fallback;
        }
    }

    private String resolveCurrentUsername() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || !StringUtils.hasText(authentication.getName())) {
            return "anonymous";
        }
        return authentication.getName();
    }

    private int defaultInt(Integer value) {
        return value == null ? 0 : value;
    }
}
