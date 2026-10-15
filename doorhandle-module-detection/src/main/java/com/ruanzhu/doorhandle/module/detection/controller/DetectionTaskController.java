package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.detection.dto.detection.CreateDetectionTaskRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.CreateDetectionTaskResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionDispositionRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionBatchPrecheckRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionBatchPrecheckResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionReworkResultRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskProgressResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskResultResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionReviewRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskAssignmentRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskTraceResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskUploadedRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadedFileItem;
import com.ruanzhu.doorhandle.module.detection.dto.detection.ResumeUploadRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.ResumeUploadResponse;
import com.ruanzhu.doorhandle.module.detection.service.DetectionTaskService;
import com.ruanzhu.doorhandle.module.detection.service.DetectionBatchPrecheckService;
import com.ruanzhu.doorhandle.module.detection.service.DetectionWorkUnitService;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitApplyRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitSubmitRequest;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionWorkUnit;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.security.core.Authentication;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/detection/tasks")
@RequiredArgsConstructor
@Slf4j
@Tag(name = "检测任务", description = "OSS 直传检测任务接口")
@Validated
public class DetectionTaskController {

    private final DetectionTaskService detectionTaskService;
    private final DetectionBatchPrecheckService detectionBatchPrecheckService;
    private final DetectionWorkUnitService detectionWorkUnitService;

    @PostMapping("/work-units/apply")
    public Result<DetectionWorkUnit> applyWorkUnit(@Valid @RequestBody DetectionWorkUnitApplyRequest request, Authentication authentication) {
        return Result.success(detectionWorkUnitService.apply(request, currentUser(authentication)));
    }

    @GetMapping("/work-units/mine")
    public Result<List<DetectionWorkUnit>> myWorkUnits(Authentication authentication) {
        return Result.success(detectionWorkUnitService.listMine(currentUser(authentication)));
    }

    @PostMapping("/work-units/{workUnitId}/submit")
    public Result<DetectionWorkUnit> submitWorkUnit(@PathVariable String workUnitId,
                                                     @Valid @RequestBody DetectionWorkUnitSubmitRequest request,
                                                     Authentication authentication) {
        return Result.success(detectionWorkUnitService.submit(workUnitId, request, currentUser(authentication)));
    }

    private String currentUser(Authentication authentication) { return authentication == null ? "anonymous" : authentication.getName(); }

    @PostMapping("/batch-precheck")
    public Result<DetectionBatchPrecheckResponse> precheckBatch(
            @Valid @RequestBody DetectionBatchPrecheckRequest request, Authentication authentication) {
        String owner = authentication == null ? "anonymous" : authentication.getName();
        return Result.success(detectionBatchPrecheckService.precheck(request, owner));
    }

    @PostMapping
    public Result<CreateDetectionTaskResponse> createTask(@Valid @RequestBody CreateDetectionTaskRequest request) {
        log.info("创建云端检测任务: files={}, modelId={}", request.getFiles().size(), request.getModelId());
        return Result.success(detectionTaskService.createTask(request));
    }

    @PostMapping("/{taskId}/upload-urls/resume")
    public Result<ResumeUploadResponse> resumeUpload(
            @PathVariable String taskId,
            @Valid @RequestBody ResumeUploadRequest request
    ) {
        log.info("续传检测任务: taskId={}, files={}", taskId, request.getFiles().size());
        return Result.success(detectionTaskService.resumeUpload(taskId, request));
    }

    @PostMapping("/{taskId}/uploaded")
    public Result<DetectionTaskProgressResponse> confirmUploaded(
            @PathVariable String taskId,
            @Valid @RequestBody DetectionTaskUploadedRequest request
    ) {
        log.info("确认检测任务上传完成: taskId={}, files={}", taskId, request.getUploadedFiles().size());
        return Result.success(detectionTaskService.confirmUploaded(taskId, request));
    }

    @GetMapping("/{taskId}")
    public Result<DetectionTaskProgressResponse> getTaskProgress(@PathVariable String taskId) {
        return Result.success(detectionTaskService.getTaskProgress(taskId));
    }

    @GetMapping("/{taskId}/result")
    public Result<DetectionTaskResultResponse> getTaskResult(@PathVariable String taskId) {
        return Result.success(detectionTaskService.getTaskResult(taskId));
    }

    @GetMapping("/{taskId}/trace")
    public Result<DetectionTaskTraceResponse> getTaskTrace(@PathVariable String taskId) {
        return Result.success(detectionTaskService.getTaskTrace(taskId));
    }

    @GetMapping("/{taskId}/quality-report")
    public Result<java.util.Map<String, Object>> getQualityReport(@PathVariable String taskId) {
        return Result.success(detectionTaskService.getQualityReport(taskId));
    }

    @GetMapping
    public Result<java.util.Map<String, Object>> listTasks(
            @RequestParam(defaultValue = "1") @Min(value = 1, message = "页码不能小于 1") int page,
            @RequestParam(defaultValue = "20") @Min(value = 1, message = "每页数量不能小于 1") @Max(value = 200, message = "每页数量不能超过 200") int size,
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String collector,
            @RequestParam(required = false) String deviceName,
            @RequestParam(required = false) String region
    ) {
        return Result.success(detectionTaskService.listTasks(page, size, keyword, status, collector, deviceName, region));
    }

    @GetMapping("/by-collector")
    public Result<java.util.Map<String, Object>> listByCollector(
            @RequestParam @NotBlank(message = "采集员不能为空") String collector,
            @RequestParam(defaultValue = "1") @Min(value = 1, message = "页码不能小于 1") int page,
            @RequestParam(defaultValue = "20") @Min(value = 1, message = "每页数量不能小于 1") @Max(value = 200, message = "每页数量不能超过 200") int size
    ) {
        return Result.success(detectionTaskService.listTasks(page, size, null, null, collector, null, null));
    }

    @GetMapping("/by-device")
    public Result<java.util.Map<String, Object>> listByDevice(
            @RequestParam @NotBlank(message = "设备名称不能为空") String deviceName,
            @RequestParam(defaultValue = "1") @Min(value = 1, message = "页码不能小于 1") int page,
            @RequestParam(defaultValue = "20") @Min(value = 1, message = "每页数量不能小于 1") @Max(value = 200, message = "每页数量不能超过 200") int size
    ) {
        return Result.success(detectionTaskService.listTasks(page, size, null, null, null, deviceName, null));
    }

    @GetMapping("/quality-queue")
    public Result<java.util.Map<String, Object>> listQualityQueue(
            @RequestParam @NotBlank(message = "质检队列不能为空") String queue,
            @RequestParam(defaultValue = "1") @Min(value = 1, message = "页码不能小于 1") int page,
            @RequestParam(defaultValue = "20") @Min(value = 1, message = "每页数量不能小于 1") @Max(value = 200, message = "每页数量不能超过 200") int size
    ) {
        return Result.success(detectionTaskService.listQualityQueue(queue, page, size));
    }

    @GetMapping("/defect-gallery")
    public Result<java.util.Map<String, Object>> listDefectGallery(
            @RequestParam(required = false) String defectType,
            @RequestParam(required = false) String severityLevel,
            @RequestParam(required = false) String deviceName,
            @RequestParam(required = false) String batchNo,
            @RequestParam(required = false) Integer modelId,
            @RequestParam(defaultValue = "1") @Min(value = 1, message = "页码不能小于 1") int page,
            @RequestParam(defaultValue = "20") @Min(value = 1, message = "每页数量不能小于 1") @Max(value = 200, message = "每页数量不能超过 200") int size
    ) {
        return Result.success(detectionTaskService.listDefectGallery(
                defectType, severityLevel, deviceName, batchNo, modelId, page, size
        ));
    }

    @GetMapping("/batch-trace")
    public Result<java.util.Map<String, Object>> getBatchTraceReport(
            @RequestParam @NotBlank(message = "批次号不能为空") String batchNo
    ) {
        return Result.success(detectionTaskService.getBatchTraceReport(batchNo));
    }

    @GetMapping("/work-order-trace")
    public Result<java.util.Map<String, Object>> getWorkOrderTraceReport(
            @RequestParam @NotBlank(message = "工单号不能为空") String workOrderNo
    ) {
        return Result.success(detectionTaskService.getWorkOrderTraceReport(workOrderNo));
    }

    @PostMapping("/{taskId}/flow")
    public Result<DetectionTaskProgressResponse> advanceTaskFlow(
            @PathVariable String taskId,
            @RequestParam @NotBlank(message = "目标流转状态不能为空") String target
    ) {
        return Result.success(detectionTaskService.advanceTaskFlow(taskId, target));
    }

    @PostMapping("/{taskId}/assignment")
    @org.springframework.security.access.prepost.PreAuthorize("hasRole('SUPERVISOR')")
    public Result<DetectionTaskProgressResponse> assignQualityTask(
            @PathVariable String taskId,
            @Valid @RequestBody DetectionTaskAssignmentRequest request
    ) {
        return Result.success(detectionTaskService.assignQualityTask(taskId, request));
    }

    @PostMapping("/{taskId}/review")
    public Result<DetectionTaskProgressResponse> reviewTask(
            @PathVariable String taskId,
            @Valid @RequestBody DetectionReviewRequest request
    ) {
        return Result.success(detectionTaskService.reviewTask(taskId, request));
    }

    @PostMapping("/{taskId}/disposition")
    public Result<DetectionTaskProgressResponse> disposeTask(
            @PathVariable String taskId,
            @Valid @RequestBody DetectionDispositionRequest request
    ) {
        return Result.success(detectionTaskService.disposeTask(taskId, request));
    }

    @PostMapping("/{taskId}/rework-result")
    public Result<DetectionTaskProgressResponse> submitReworkResult(
            @PathVariable String taskId,
            @Valid @RequestBody DetectionReworkResultRequest request
    ) {
        return Result.success(detectionTaskService.submitReworkResult(taskId, request));
    }

    @PostMapping("/{taskId}/retry")
    public Result<DetectionTaskProgressResponse> retryTask(@PathVariable String taskId) {
        return Result.success(detectionTaskService.retryTask(taskId));
    }

    @PostMapping("/{taskId}/mark-uploaded")
    public Result<Void> markUploaded(
            @PathVariable String taskId,
            @Valid @RequestBody DetectionTaskUploadedRequest request
    ) {
        detectionTaskService.markUploaded(taskId, request.getUploadedFiles());
        return Result.success(null);
    }
}
