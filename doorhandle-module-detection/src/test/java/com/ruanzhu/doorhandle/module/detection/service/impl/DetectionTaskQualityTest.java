package com.ruanzhu.doorhandle.module.detection.service.impl;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionDispositionRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionReworkResultRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionReviewRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskAssignmentRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskProgressResponse;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class DetectionTaskQualityTest {

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
    void advanceTaskFlowCannotFabricateAReviewConclusion() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_123");
        task.setStatus("COMPLETED");
        task.setFlowStatus("PENDING_REVIEW");
        task.setReviewStatus("PENDING");

        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);

        assertThrows(BusinessException.class, () -> fixture.service.advanceTaskFlow("det_123", "CONFIRMED"));
        verify(fixture.detectionTaskMapper, Mockito.never()).updateById(any(DetectionTask.class));
    }

    @Test
    void advanceTaskFlowRejectsDispositionBypass() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_bypass");
        task.setStatus("COMPLETED");
        task.setFlowStatus("CONFIRMED");
        task.setReviewStatus("REVIEWED");
        task.setReviewedAt(LocalDateTime.of(2026, 6, 10, 10, 0));

        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);

        BusinessException exception = assertThrows(
                BusinessException.class,
                () -> fixture.service.advanceTaskFlow("det_bypass", "RELEASED")
        );

        assertEquals(409, exception.getCode());
    }

    @Test
    void reviewTaskStoresHumanConclusionAndConfirmsFlow() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_review");
        task.setStatus("COMPLETED");
        task.setFlowStatus("PENDING_REVIEW");
        task.setReviewStatus("PENDING");

        DetectionReviewRequest request = new DetectionReviewRequest();
        request.setReviewConclusion("CONFIRMED_DEFECT");
        request.setSeverityLevel("MAJOR");
        request.setConfirmedDefectCount(3);
        request.setFalsePositiveCount(1);
        request.setReviewRemark("锈蚀区域明显，1 张疑似误报");

        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);

        DetectionTaskProgressResponse response = fixture.service.reviewTask("det_review", request);

        assertEquals("REVIEWED", response.getReviewStatus());
        assertEquals("CONFIRMED_DEFECT", response.getReviewConclusion());
        assertEquals("MAJOR", response.getSeverityLevel());
        assertEquals("CONFIRMED", response.getFlowStatus());

        ArgumentCaptor<DetectionTask> taskCaptor = ArgumentCaptor.forClass(DetectionTask.class);
        verify(fixture.detectionTaskMapper).updateById(taskCaptor.capture());
        DetectionTask reviewedTask = taskCaptor.getValue();
        assertEquals("REVIEWED", reviewedTask.getReviewStatus());
        assertEquals("CONFIRMED_DEFECT", reviewedTask.getReviewConclusion());
        assertEquals("MAJOR", reviewedTask.getSeverityLevel());
        assertEquals(3, reviewedTask.getConfirmedDefectCount());
        assertEquals(1, reviewedTask.getFalsePositiveCount());
        assertEquals("锈蚀区域明显，1 张疑似误报", reviewedTask.getReviewRemark());
        assertNotNull(reviewedTask.getReviewedAt());
    }

    @Test
    void reviewTaskRejectsNegativeReviewCounts() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_review");
        task.setStatus("COMPLETED");
        task.setFlowStatus("PENDING_REVIEW");
        task.setReviewStatus("PENDING");

        DetectionReviewRequest request = new DetectionReviewRequest();
        request.setConfirmedDefectCount(-1);
        request.setFalsePositiveCount(0);

        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);

        BusinessException exception = assertThrows(
                BusinessException.class,
                () -> fixture.service.reviewTask("det_review", request)
        );

        assertEquals("复核数量不能为负数", exception.getMessage());
    }

    @Test
    void reviewTaskAcceptsLegacyReviewAliases() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_review_alias");
        task.setStatus("COMPLETED");
        task.setFlowStatus("PENDING_REVIEW");
        task.setReviewStatus("PENDING");

        DetectionReviewRequest request = new DetectionReviewRequest();
        request.setReviewConclusion("PASS");
        request.setSeverityLevel("LOW");

        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);

        DetectionTaskProgressResponse response = fixture.service.reviewTask("det_review_alias", request);

        assertEquals("NORMAL_RELEASE", response.getReviewConclusion());
        assertEquals("MINOR", response.getSeverityLevel());
    }

    @Test
    void assignQualityTaskStoresStationOwnerAndMovesToReviewing() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_assign");
        task.setStatus("COMPLETED");
        task.setFlowStatus("PENDING_REVIEW");
        task.setReviewStatus("PENDING");
        task.setReviewStatus("PENDING");

        DetectionTaskAssignmentRequest request = new DetectionTaskAssignmentRequest();
        request.setQualityStation("QC-STATION-01");
        request.setAssignee("qa-user");
        request.setDueAt("2026-06-11T18:30:00+08:00");
        request.setAssignmentRemark("优先复核锈蚀疑似缺陷");

        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);

        DetectionTaskProgressResponse response = fixture.service.assignQualityTask("det_assign", request);

        assertEquals("REVIEWING", response.getFlowStatus());
        assertEquals("QC-STATION-01", response.getQualityStation());
        assertEquals("qa-user", response.getAssignee());
        assertEquals("优先复核锈蚀疑似缺陷", response.getAssignmentRemark());

        ArgumentCaptor<DetectionTask> taskCaptor = ArgumentCaptor.forClass(DetectionTask.class);
        verify(fixture.detectionTaskMapper).updateById(taskCaptor.capture());
        DetectionTask assignedTask = taskCaptor.getValue();
        assertEquals("QC-STATION-01", assignedTask.getQualityStation());
        assertEquals("qa-user", assignedTask.getAssignee());
        assertEquals("REVIEWING", assignedTask.getFlowStatus());
        assertNotNull(assignedTask.getAssignedAt());
        assertNotNull(assignedTask.getDueAt());
    }

    @Test
    void reviewTaskRejectsDisposedTask() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_review_done");
        task.setStatus("COMPLETED");
        task.setFlowStatus("RELEASED");
        task.setReviewStatus("REVIEWED");
        task.setReviewedAt(LocalDateTime.of(2026, 6, 10, 10, 0));
        task.setDispositionStatus("DISPOSED");
        task.setDisposedAt(LocalDateTime.of(2026, 6, 10, 11, 10));

        DetectionReviewRequest request = new DetectionReviewRequest();
        request.setReviewConclusion("CONFIRMED_DEFECT");
        request.setSeverityLevel("MAJOR");

        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);

        BusinessException exception = assertThrows(
                BusinessException.class,
                () -> fixture.service.reviewTask("det_review_done", request)
        );

        assertEquals(409, exception.getCode());
    }

    @Test
    void disposeTaskStoresQualityDispositionAndMovesToRework() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_dispose");
        task.setStatus("COMPLETED");
        task.setFlowStatus("CONFIRMED");
        task.setReviewStatus("REVIEWED");
        task.setReviewedAt(LocalDateTime.of(2026, 6, 10, 10, 0));
        task.setReviewConclusion("CONFIRMED_DEFECT");
        task.setSeverityLevel("MAJOR");

        DetectionDispositionRequest request = new DetectionDispositionRequest();
        request.setDispositionAction("REWORK");
        request.setDispositionRemark("缺陷确认，转返工处理");

        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);

        DetectionTaskProgressResponse response = fixture.service.disposeTask("det_dispose", request);

        assertEquals("DISPOSED", response.getDispositionStatus());
        assertEquals("REWORK", response.getDispositionAction());
        assertEquals("REWORK_REQUIRED", response.getFlowStatus());
        assertEquals(Boolean.FALSE, response.getRecheckRequired());

        ArgumentCaptor<DetectionTask> taskCaptor = ArgumentCaptor.forClass(DetectionTask.class);
        verify(fixture.detectionTaskMapper).updateById(taskCaptor.capture());
        DetectionTask disposedTask = taskCaptor.getValue();
        assertEquals("DISPOSED", disposedTask.getDispositionStatus());
        assertEquals("REWORK", disposedTask.getDispositionAction());
        assertEquals("缺陷确认，转返工处理", disposedTask.getDispositionRemark());
        assertEquals("REWORK_REQUIRED", disposedTask.getFlowStatus());
        assertNotNull(disposedTask.getDisposedAt());
    }

    @Test
    void disposeTaskRejectsReleaseForConfirmedDefect() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_dispose");
        task.setStatus("COMPLETED");
        task.setFlowStatus("CONFIRMED");
        task.setReviewStatus("REVIEWED");
        task.setReviewedAt(LocalDateTime.of(2026, 6, 10, 10, 0));
        task.setReviewConclusion("CONFIRMED_DEFECT");
        task.setSeverityLevel("CRITICAL");

        DetectionDispositionRequest request = new DetectionDispositionRequest();
        request.setDispositionAction("RELEASE");

        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);

        BusinessException exception = assertThrows(
                BusinessException.class,
                () -> fixture.service.disposeTask("det_dispose", request)
        );

        assertEquals(409, exception.getCode());
    }

    @Test
    void disposeTaskRejectsRepeatedDisposition() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_dispose_done");
        task.setStatus("COMPLETED");
        task.setFlowStatus("RELEASED");
        task.setReviewStatus("REVIEWED");
        task.setReviewedAt(LocalDateTime.of(2026, 6, 10, 10, 0));
        task.setReviewConclusion("NORMAL_RELEASE");
        task.setDispositionStatus("DISPOSED");
        task.setDispositionAction("RELEASE");
        task.setDisposedAt(LocalDateTime.of(2026, 6, 10, 11, 10));

        DetectionDispositionRequest request = new DetectionDispositionRequest();
        request.setDispositionAction("SCRAP");

        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);

        BusinessException exception = assertThrows(
                BusinessException.class,
                () -> fixture.service.disposeTask("det_dispose_done", request)
        );

        assertEquals(409, exception.getCode());
    }

    @Test
    void submitReworkResultUsesAuthenticatedOperatorAndRoutesToRecheck() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_rework");
        task.setStatus("COMPLETED");
        task.setFlowStatus("REWORK_REQUIRED");
        task.setReviewStatus("REVIEWED");
        task.setReviewedAt(LocalDateTime.of(2026, 6, 10, 10, 0));
        task.setDispositionStatus("DISPOSED");
        task.setDispositionAction("REWORK");
        task.setDisposedAt(LocalDateTime.of(2026, 6, 10, 11, 0));

        DetectionReworkResultRequest request = new DetectionReworkResultRequest();
        request.setReworkResult("HANDLE_REPLACED");
        request.setReworkOperator("repair-user");
        request.setReworkRemark("已更换门把手锁扣组件");
        request.setRecheckRequired(true);

        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);
        when(fixture.detectionTaskMapper.clearDispositionForRework("det_rework")).thenReturn(1);

        DetectionTaskProgressResponse response = fixture.service.submitReworkResult("det_rework", request);

        assertEquals("RECHECK_REQUIRED", response.getFlowStatus());
        assertEquals("HANDLE_REPLACED", response.getReworkResult());
        assertEquals("admin", response.getReworkOperator());
        assertEquals(Boolean.TRUE, response.getRecheckRequired());

        ArgumentCaptor<DetectionTask> taskCaptor = ArgumentCaptor.forClass(DetectionTask.class);
        verify(fixture.detectionTaskMapper).updateById(taskCaptor.capture());
        DetectionTask reworkedTask = taskCaptor.getValue();
        assertEquals("HANDLE_REPLACED", reworkedTask.getReworkResult());
        assertEquals("admin", reworkedTask.getReworkOperator());
        assertEquals("已更换门把手锁扣组件", reworkedTask.getReworkRemark());
        assertEquals("RECHECK_REQUIRED", reworkedTask.getFlowStatus());
        assertEquals("PENDING", reworkedTask.getReviewStatus());
        assertNull(reworkedTask.getDispositionStatus());
        assertNull(reworkedTask.getDispositionAction());
        assertNull(reworkedTask.getDispositionOperator());
        assertNull(reworkedTask.getDisposedAt());
        assertNotNull(reworkedTask.getReworkCompletedAt());
    }

    @Test
    void listQualityQueueReturnsActionableTaskRecords() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_queue");
        task.setStatus("COMPLETED");
        task.setFlowStatus("PENDING_REVIEW");
        task.setReviewStatus("PENDING");
        task.setReviewStatus("PENDING");
        task.setTotalImages(2);
        task.setCreatedAt(LocalDateTime.of(2026, 6, 10, 10, 0));

        Mockito.doAnswer(invocation -> {
            com.baomidou.mybatisplus.extension.plugins.pagination.Page<DetectionTask> page = invocation.getArgument(0);
            page.setRecords(List.of(task));
            page.setTotal(1);
            return page;
        }).when(fixture.detectionTaskMapper).selectPage(any(), any());

        java.util.Map<String, Object> result = fixture.service.listQualityQueue("PENDING_REVIEW", 1, 20);

        assertEquals("PENDING_REVIEW", result.get("queue"));
        assertEquals(1L, result.get("total"));
        @SuppressWarnings("unchecked")
        List<DetectionTaskProgressResponse> records = (List<DetectionTaskProgressResponse>) result.get("records");
        assertEquals(1, records.size());
        assertEquals("det_queue", records.get(0).getTaskId());
        assertEquals("PENDING_REVIEW", records.get(0).getFlowStatus());
    }

    @Test
    void listQualityQueueRejectsUnsupportedQueue() {
        BusinessException exception = assertThrows(
                BusinessException.class,
                () -> fixture.service.listQualityQueue("UNKNOWN", 1, 20)
        );

        assertEquals("不支持的质检队列: UNKNOWN", exception.getMessage());
    }
}
