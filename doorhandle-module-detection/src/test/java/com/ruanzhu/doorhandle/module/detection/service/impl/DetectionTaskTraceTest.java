package com.ruanzhu.doorhandle.module.detection.service.impl;

import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskTraceResponse;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskProgressResponse;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

class DetectionTaskTraceTest {

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
    void getBatchTraceReportAggregatesBatchInspectionAndQuality() {
        DetectionTask task1 = new DetectionTask();
        task1.setTaskId("det_batch_1");
        task1.setBatchNo("2026-06-11_SH_CAM01_A");
        task1.setWorkOrderNo("WO-1");
        task1.setStatus("COMPLETED");
        task1.setFlowStatus("RELEASED");
        task1.setCaptureDate("2026-06-11");
        task1.setRegion("上海");
        task1.setCollector("collector-a");
        task1.setDeviceName("CAM01");
        task1.setModelId(7);
        task1.setModelVersion("v1");
        task1.setTotalImages(10);
        task1.setProcessedImages(10);
        task1.setSuccessfulImages(9);
        task1.setFailedImages(1);
        task1.setDefectCount(3);
        task1.setConfirmedDefectCount(2);
        task1.setFalsePositiveCount(1);
        task1.setPrimaryDefectType("scratch");
        task1.setMaxDefectSeverity("MAJOR");
        task1.setReviewStatus("REVIEWED");
        task1.setDispositionStatus("DISPOSED");
        task1.setCreatedAt(LocalDateTime.of(2026, 6, 11, 9, 0));
        task1.setFinishedAt(LocalDateTime.of(2026, 6, 11, 9, 10));
        task1.setUpdatedAt(LocalDateTime.of(2026, 6, 11, 9, 20));

        DetectionTask task2 = new DetectionTask();
        task2.setTaskId("det_batch_2");
        task2.setBatchNo("2026-06-11_SH_CAM01_A");
        task2.setWorkOrderNo("WO-2");
        task2.setStatus("COMPLETED");
        task2.setFlowStatus("PENDING_REVIEW");
        task2.setCaptureDate("2026-06-11");
        task2.setRegion("上海");
        task2.setCollector("collector-a");
        task2.setDeviceName("CAM02");
        task2.setModelId(8);
        task2.setModelVersion("v2");
        task2.setTotalImages(5);
        task2.setProcessedImages(5);
        task2.setSuccessfulImages(5);
        task2.setFailedImages(0);
        task2.setDefectCount(0);
        task2.setReviewStatus("PENDING");
        task2.setCreatedAt(LocalDateTime.of(2026, 6, 11, 10, 0));
        task2.setUpdatedAt(LocalDateTime.of(2026, 6, 11, 10, 5));

        when(fixture.detectionTaskMapper.selectList(any())).thenReturn(List.of(task1, task2));

        java.util.Map<String, Object> report = fixture.service.getBatchTraceReport("2026-06-11_SH_CAM01_A");

        assertEquals("BATCH_TRACE_REPORT", report.get("reportType"));
        @SuppressWarnings("unchecked")
        Map<String, Object> inspection = (Map<String, Object>) report.get("inspection");
        assertEquals(15, inspection.get("totalImages"));
        assertEquals(3, inspection.get("defectCount"));
        assertEquals(0.2, (Double) inspection.get("defectRate"), 0.0001);

        @SuppressWarnings("unchecked")
        Map<String, Object> quality = (Map<String, Object>) report.get("quality");
        assertEquals(1L, quality.get("pendingReview"));
        assertEquals(1L, quality.get("reviewed"));
        assertEquals(0.5, (Double) quality.get("reviewCompletionRate"), 0.0001);

        @SuppressWarnings("unchecked")
        Map<String, Object> distribution = (Map<String, Object>) report.get("distribution");
        @SuppressWarnings("unchecked")
        Map<String, Long> deviceDistribution = (Map<String, Long>) distribution.get("device");
        assertEquals(1L, deviceDistribution.get("CAM01"));
        assertEquals(1L, deviceDistribution.get("CAM02"));

        @SuppressWarnings("unchecked")
        List<DetectionTaskProgressResponse> records = (List<DetectionTaskProgressResponse>) report.get("records");
        assertEquals(2, records.size());
        assertEquals("det_batch_1", records.get(0).getTaskId());
    }

    @Test
    void getWorkOrderTraceReportAggregatesAcrossBatches() {
        DetectionTask task1 = new DetectionTask();
        task1.setTaskId("det_work_order_1");
        task1.setBatchNo("BATCH-A");
        task1.setWorkOrderNo("WO-20260611-001");
        task1.setStatus("COMPLETED");
        task1.setFlowStatus("REWORK_REQUIRED");
        task1.setRegion("上海");
        task1.setCollector("collector-a");
        task1.setDeviceName("CAM01");
        task1.setModelId(7);
        task1.setModelVersion("v1");
        task1.setTotalImages(12);
        task1.setSuccessfulImages(12);
        task1.setDefectCount(4);
        task1.setConfirmedDefectCount(3);
        task1.setReviewStatus("REVIEWED");
        task1.setDispositionStatus("PENDING");
        task1.setCreatedAt(LocalDateTime.of(2026, 6, 11, 9, 0));
        task1.setUpdatedAt(LocalDateTime.of(2026, 6, 11, 9, 30));

        DetectionTask task2 = new DetectionTask();
        task2.setTaskId("det_work_order_2");
        task2.setBatchNo("BATCH-B");
        task2.setWorkOrderNo("WO-20260611-001");
        task2.setStatus("COMPLETED");
        task2.setFlowStatus("RELEASED");
        task2.setRegion("苏州");
        task2.setCollector("collector-b");
        task2.setDeviceName("CAM02");
        task2.setModelId(7);
        task2.setModelVersion("v1");
        task2.setTotalImages(8);
        task2.setSuccessfulImages(8);
        task2.setDefectCount(0);
        task2.setReviewStatus("REVIEWED");
        task2.setDispositionStatus("DISPOSED");
        task2.setCreatedAt(LocalDateTime.of(2026, 6, 11, 10, 0));
        task2.setUpdatedAt(LocalDateTime.of(2026, 6, 11, 10, 30));

        when(fixture.detectionTaskMapper.selectList(any())).thenReturn(List.of(task1, task2));

        java.util.Map<String, Object> report = fixture.service.getWorkOrderTraceReport("WO-20260611-001");

        assertEquals("WORK_ORDER_TRACE_REPORT", report.get("reportType"));
        assertEquals("WO-20260611-001", report.get("workOrderNo"));
        @SuppressWarnings("unchecked")
        Map<String, Object> summary = (Map<String, Object>) report.get("summary");
        assertEquals(2, summary.get("taskCount"));
        @SuppressWarnings("unchecked")
        List<String> batchNos = (List<String>) summary.get("batchNos");
        assertEquals(List.of("BATCH-A", "BATCH-B"), batchNos);

        @SuppressWarnings("unchecked")
        Map<String, Object> inspection = (Map<String, Object>) report.get("inspection");
        assertEquals(20, inspection.get("totalImages"));
        assertEquals(4, inspection.get("defectCount"));

        @SuppressWarnings("unchecked")
        Map<String, Object> quality = (Map<String, Object>) report.get("quality");
        assertEquals(1L, quality.get("disposed"));
        assertEquals(1L, quality.get("reworkRequired"));
        assertEquals(1L, quality.get("closed"));
        assertEquals(0.5, (Double) quality.get("closureRate"), 0.0001);
    }

    @Test
    void listDefectGalleryReturnsTraceableDefectRecords() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_gallery");
        task.setStatus("COMPLETED");
        task.setFlowStatus("PENDING_REVIEW");
        task.setBatchNo("BATCH-001");
        task.setWorkOrderNo("WO-001");
        task.setDeviceName("CAM-01");
        task.setModelId(7);
        task.setModelVersion("v2");
        task.setDefectEvidenceJson("[{\"imageName\":\"img001.jpg\",\"defectType\":\"Rusty\",\"confidence\":0.92,\"area\":3600,\"positionRegion\":\"CENTER\",\"severityLevel\":\"MAJOR\"}]");
        task.setDefectCount(1);
        task.setPrimaryDefectType("Rusty");
        task.setMaxDefectSeverity("MAJOR");
        task.setCreatedAt(LocalDateTime.of(2026, 6, 10, 10, 0));

        Mockito.doAnswer(invocation -> {
            com.baomidou.mybatisplus.extension.plugins.pagination.Page<DetectionTask> page = invocation.getArgument(0);
            page.setRecords(List.of(task));
            page.setTotal(1);
            return page;
        }).when(fixture.detectionTaskMapper).selectPage(any(), any());

        java.util.Map<String, Object> result = fixture.service.listDefectGallery(
                "Rusty", "MAJOR", "CAM-01", "BATCH-001", 7, 1, 20
        );

        assertEquals(1L, result.get("total"));
        assertEquals("Rusty", result.get("defectType"));
        assertEquals("MAJOR", result.get("severityLevel"));
        @SuppressWarnings("unchecked")
        List<DetectionTaskTraceResponse> records = (List<DetectionTaskTraceResponse>) result.get("records");
        assertEquals(1, records.size());
        assertEquals("det_gallery", records.get(0).getTaskId());
        assertEquals(1, records.get(0).getDefectCount());
        assertEquals("Rusty", records.get(0).getPrimaryDefectType());
        assertEquals(1, records.get(0).getDefectEvidence().size());
    }

    @Test
    void getQualityReportBuildsReportReadyTaskSnapshot() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_report");
        task.setWorkflowUuid("wf-report");
        task.setBatchNo("BATCH-20260610");
        task.setWorkOrderNo("WO-20260610-001");
        task.setStatus("COMPLETED");
        task.setFlowStatus("RELEASED");
        task.setModelId(7);
        task.setModelVersion("v2");
        task.setCaptureDate("2026-06-10");
        task.setRegion("上海");
        task.setCollector("张三");
        task.setDeviceName("CAM-01");
        task.setImageFolderName("门把手批次A");
        task.setTotalImages(10);
        task.setSuccessfulImages(9);
        task.setFailedImages(1);
        task.setStatisticsJson("{\"classCounts\":{\"Rusty\":2},\"missDetectionRate\":0.01}");
        task.setReviewStatus("REVIEWED");
        task.setReviewConclusion("NORMAL_RELEASE");
        task.setSeverityLevel("MINOR");
        task.setConfirmedDefectCount(0);
        task.setFalsePositiveCount(2);
        task.setReviewRemark("两处为误报，准予放行");
        task.setReviewer("qa-user");
        task.setReviewedAt(LocalDateTime.of(2026, 6, 10, 11, 0));
        task.setDispositionStatus("DISPOSED");
        task.setDispositionAction("RELEASE");
        task.setDispositionRemark("质检放行");
        task.setDispositionOperator("leader");
        task.setDisposedAt(LocalDateTime.of(2026, 6, 10, 11, 10));
        task.setOriginalImageKeysJson("[\"detection/source/img001.jpg\"]");
        task.setPreviewImageKeysJson("[\"detection/result/img001.jpg\"]");
        task.setResultJsonOssKey("detection/result/result.json");
        task.setCreatedAt(LocalDateTime.of(2026, 6, 10, 10, 0));
        task.setStartedAt(LocalDateTime.of(2026, 6, 10, 10, 2));
        task.setFinishedAt(LocalDateTime.of(2026, 6, 10, 10, 8));

        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);
        when(fixture.ossStorageService.isConfigured()).thenReturn(true);

        java.util.Map<String, Object> report = fixture.service.getQualityReport("det_report");

        assertEquals("QUALITY_INSPECTION_REPORT", report.get("reportType"));
        assertEquals("det_report", report.get("taskId"));
        assertEquals("WO-20260610-001", report.get("workOrderNo"));
        assertEquals("RELEASED", report.get("flowStatus"));

        @SuppressWarnings("unchecked")
        java.util.Map<String, Object> inspection = (java.util.Map<String, Object>) report.get("inspection");
        assertEquals(10, inspection.get("totalImages"));
        assertEquals(9, inspection.get("successfulImages"));
        assertEquals(1, inspection.get("failedImages"));

        @SuppressWarnings("unchecked")
        java.util.Map<String, Object> review = (java.util.Map<String, Object>) report.get("review");
        assertEquals("REVIEWED", review.get("reviewStatus"));
        assertEquals("NORMAL_RELEASE", review.get("reviewConclusion"));

        @SuppressWarnings("unchecked")
        java.util.Map<String, Object> disposition = (java.util.Map<String, Object>) report.get("disposition");
        assertEquals("DISPOSED", disposition.get("dispositionStatus"));
        assertEquals("RELEASE", disposition.get("dispositionAction"));

        @SuppressWarnings("unchecked")
        java.util.Map<String, Object> evidence = (java.util.Map<String, Object>) report.get("evidence");
        assertEquals(1, ((List<?>) evidence.get("originalImages")).size());
        assertEquals(1, ((List<?>) evidence.get("previewImages")).size());
        assertTrue(((String) evidence.get("resultJsonUrl")).contains("detection%2Fresult%2Fresult.json"));

        assertEquals(5, ((List<?>) report.get("timeline")).size());
    }

    @Test
    void getTaskTraceBuildsEvidenceChainForFinishedReviewedTask() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_trace");
        task.setWorkflowUuid("wf-001");
        task.setBatchNo("BATCH-001");
        task.setWorkOrderNo("WO-20260610-001");
        task.setStatus("COMPLETED");
        task.setFlowStatus("CONFIRMED");
        task.setModelId(7);
        task.setModelVersion("v2");
        task.setCaptureDate("2026-06-10");
        task.setRegion("上海");
        task.setCollector("张三");
        task.setDeviceName("CAM-01");
        task.setImageFolderName("门把手批次A");
        task.setSourceOssPrefix("detection/source/");
        task.setResultOssPrefix("detection/result/");
        task.setResultJsonOssKey("detection/result/detection_results.json");
        task.setOriginalImageKeysJson("[\"detection/source/img001.jpg\",\"detection/source/img002.jpg\"]");
        task.setPreviewImageKeysJson("[\"detection/result/img001.jpg\"]");
        task.setDefectEvidenceJson("[{\"imageName\":\"img001.jpg\",\"defectType\":\"Rusty\",\"confidence\":0.92,\"area\":3600,\"positionRegion\":\"CENTER\",\"severityLevel\":\"MAJOR\",\"bbox\":{\"x\":12,\"y\":18,\"width\":90,\"height\":40}}]");
        task.setDefectCount(1);
        task.setPrimaryDefectType("Rusty");
        task.setMaxDefectSeverity("MAJOR");
        task.setReviewStatus("REVIEWED");
        task.setReviewConclusion("CONFIRMED_DEFECT");
        task.setSeverityLevel("CRITICAL");
        task.setConfirmedDefectCount(2);
        task.setFalsePositiveCount(1);
        task.setReviewRemark("锈蚀严重，保留一张误报样本");
        task.setReviewer("qa-user");
        task.setCreatedAt(LocalDateTime.of(2026, 6, 10, 9, 0));
        task.setStartedAt(LocalDateTime.of(2026, 6, 10, 9, 5));
        task.setFinishedAt(LocalDateTime.of(2026, 6, 10, 9, 8));
        task.setReviewedAt(LocalDateTime.of(2026, 6, 10, 9, 20));

        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);
        when(fixture.ossStorageService.isConfigured()).thenReturn(true);

        DetectionTaskTraceResponse response = fixture.service.getTaskTrace("det_trace");

        assertEquals("det_trace", response.getTaskId());
        assertEquals("BATCH-001", response.getBatchNo());
        assertEquals("WO-20260610-001", response.getWorkOrderNo());
        assertEquals("CAM-01", response.getDeviceName());
        assertEquals(7, response.getModelId());
        assertEquals("v2", response.getModelVersion());
        assertEquals(2, response.getOriginalImages().size());
        assertTrue(response.getOriginalImages().get(0).getPreviewUrl().contains("detection%2Fsource%2Fimg001.jpg"));
        assertEquals("detection/result/detection_results.json", response.getResultJsonKey());
        assertTrue(response.getResultJsonUrl().contains("detection%2Fresult%2Fdetection_results.json"));
        assertEquals("CONFIRMED_DEFECT", response.getReviewConclusion());
        assertEquals("CRITICAL", response.getSeverityLevel());
        assertEquals(1, response.getDefectEvidence().size());
        assertEquals("Rusty", response.getDefectEvidence().get(0).get("defectType"));
        assertEquals("CENTER", response.getDefectEvidence().get(0).get("positionRegion"));
        assertEquals(1, response.getDefectCount());
        assertEquals("Rusty", response.getPrimaryDefectType());
        assertEquals("MAJOR", response.getMaxDefectSeverity());
        assertEquals(2, response.getConfirmedDefectCount());
        assertEquals(1, response.getFalsePositiveCount());
        assertEquals(4, response.getTimeline().size());
    }
}
