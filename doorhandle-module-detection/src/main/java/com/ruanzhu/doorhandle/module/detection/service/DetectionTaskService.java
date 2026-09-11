package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.module.detection.dto.detection.CreateDetectionTaskRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.CreateDetectionTaskResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionDispositionRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionReworkResultRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskProgressResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskResultResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskAssignmentRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskTraceResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionReviewRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskUploadedRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionUploadedFileItem;
import com.ruanzhu.doorhandle.module.detection.dto.detection.ResumeUploadRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.ResumeUploadResponse;

import java.util.List;
import java.util.Map;

public interface DetectionTaskService {
    CreateDetectionTaskResponse createTask(CreateDetectionTaskRequest request);

    ResumeUploadResponse resumeUpload(String taskId, ResumeUploadRequest request);

    DetectionTaskProgressResponse confirmUploaded(String taskId, DetectionTaskUploadedRequest request);

    DetectionTaskProgressResponse getTaskProgress(String taskId);

    DetectionTaskResultResponse getTaskResult(String taskId);

    DetectionTaskTraceResponse getTaskTrace(String taskId);

    Map<String, Object> getQualityReport(String taskId);

    Map<String, Object> listTasks(int page, int size, String keyword, String status,
                                  String collector, String deviceName, String region);

    Map<String, Object> listQualityQueue(String queue, int page, int size);

    Map<String, Object> listDefectGallery(String defectType, String severityLevel, String deviceName,
                                          String batchNo, Integer modelId, int page, int size);

    Map<String, Object> getBatchTraceReport(String batchNo);

    Map<String, Object> getWorkOrderTraceReport(String workOrderNo);

    DetectionTaskProgressResponse advanceTaskFlow(String taskId, String targetFlowStatus);

    DetectionTaskProgressResponse assignQualityTask(String taskId, DetectionTaskAssignmentRequest request);

    DetectionTaskProgressResponse reviewTask(String taskId, DetectionReviewRequest request);

    DetectionTaskProgressResponse disposeTask(String taskId, DetectionDispositionRequest request);

    DetectionTaskProgressResponse submitReworkResult(String taskId, DetectionReworkResultRequest request);

    DetectionTaskProgressResponse retryTask(String taskId);

    void markUploaded(String taskId, List<DetectionUploadedFileItem> uploadedFiles);
}
