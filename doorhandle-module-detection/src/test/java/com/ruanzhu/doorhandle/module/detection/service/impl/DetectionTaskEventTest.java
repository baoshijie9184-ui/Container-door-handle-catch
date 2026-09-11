package com.ruanzhu.doorhandle.module.detection.service.impl;

import com.ruanzhu.doorhandle.contracts.detection.DetectionTaskFinishedEvent;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import org.springframework.security.core.context.SecurityContextHolder;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class DetectionTaskEventTest {

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
    void applyFinishedEventUsesStartedAtFromWorkerEvent() {
        DetectionTask task = new DetectionTask();
        task.setId(1L);
        task.setTaskId("det_123");
        task.setStatus("QUEUED");
        task.setStage("QUEUED");
        task.setTotalImages(1);
        task.setDispatchId("dispatch-1");

        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);

        fixture.service.applyFinishedEvent(DetectionTaskFinishedEvent.builder()
                .taskId("det_123")
                .eventId("event-1")
                .dispatchId("dispatch-1")
                .status("COMPLETED")
                .resultOssPrefix("detection/task/Result/")
                .resultJsonKey("detection/task/Result/detection_results.json")
                .previewKeys(List.of("detection/task/Result/img001.jpg"))
                .statistics(java.util.Map.of("classCounts", java.util.Map.of("Normal", 1)))
                .totalImages(1)
                .successfulImages(1)
                .failedImages(0)
                .startedAt("2026-05-20T16:12:00+08:00")
                .finishedAt("2026-05-20T16:12:08+08:00")
                .build());

        ArgumentCaptor<DetectionTask> taskCaptor = ArgumentCaptor.forClass(DetectionTask.class);
        verify(fixture.detectionTaskMapper, org.mockito.Mockito.atLeastOnce()).updateById(taskCaptor.capture());
        DetectionTask updatedTask = taskCaptor.getAllValues().get(taskCaptor.getAllValues().size() - 1);

        assertEquals(LocalDateTime.of(2026, 5, 20, 16, 12, 0), updatedTask.getStartedAt());
        assertEquals(LocalDateTime.of(2026, 5, 20, 16, 12, 8), updatedTask.getFinishedAt());
        assertEquals("PENDING_REVIEW", updatedTask.getFlowStatus());
    }

    @Test
    void completionNotificationUsesOutboundPort() {
        DetectionTask task = new DetectionTask();
        task.setId(1L);
        task.setTaskId("det_chat");
        task.setSessionId("sess_alice_1");
        task.setStatus("QUEUED");
        task.setStage("QUEUED");
        task.setTotalImages(1);
        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);
        fixture.service.applyFinishedEvent(DetectionTaskFinishedEvent.builder()
                .taskId(task.getTaskId()).eventId("event-chat").status("COMPLETED")
                .totalImages(1).successfulImages(1).failedImages(0).build());

        verify(fixture.detectionNotificationPort).notifyTaskCompleted(eq(task.getSessionId()), any());
    }

    @Test
    void applyFinishedEventDoesNotResetReviewedDisposedTaskOnDuplicateEvent() {
        DetectionTask task = new DetectionTask();
        task.setId(1L);
        task.setTaskId("det_done");
        task.setStatus("COMPLETED");
        task.setStage("COMPLETED");
        task.setFlowStatus("RELEASED");
        task.setReviewStatus("REVIEWED");
        task.setReviewConclusion("NORMAL_RELEASE");
        task.setDispositionStatus("DISPOSED");
        task.setDispositionAction("RELEASE");
        task.setDispositionRemark("质检放行");
        task.setDispositionOperator("qa-leader");
        task.setDisposedAt(LocalDateTime.of(2026, 6, 10, 11, 10));
        task.setTotalImages(1);
        task.setDispatchId("dispatch-done");

        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);

        fixture.service.applyFinishedEvent(DetectionTaskFinishedEvent.builder()
                .taskId("det_done")
                .eventId("event-done")
                .dispatchId("dispatch-done")
                .status("COMPLETED")
                .resultOssPrefix("detection/task/Result/")
                .resultJsonKey("detection/task/Result/detection_results.json")
                .previewKeys(List.of("detection/task/Result/img001.jpg"))
                .statistics(java.util.Map.of("classCounts", java.util.Map.of("Normal", 1)))
                .totalImages(1)
                .successfulImages(1)
                .failedImages(0)
                .finishedAt("2026-06-10T11:30:00+08:00")
                .build());

        ArgumentCaptor<DetectionTask> taskCaptor = ArgumentCaptor.forClass(DetectionTask.class);
        verify(fixture.detectionTaskMapper, org.mockito.Mockito.atLeastOnce()).updateById(taskCaptor.capture());
        DetectionTask updatedTask = taskCaptor.getAllValues().get(taskCaptor.getAllValues().size() - 1);

        assertEquals("COMPLETED", updatedTask.getStatus());
        assertEquals("RELEASED", updatedTask.getFlowStatus());
        assertEquals("REVIEWED", updatedTask.getReviewStatus());
        assertEquals("DISPOSED", updatedTask.getDispositionStatus());
        assertEquals("RELEASE", updatedTask.getDispositionAction());
        assertEquals("qa-leader", updatedTask.getDispositionOperator());
    }

    @Test
    void applyFinishedEventStoresStructuredDefectEvidence() {
        DetectionTask task = new DetectionTask();
        task.setId(1L);
        task.setTaskId("det_defect");
        task.setStatus("QUEUED");
        task.setStage("QUEUED");
        task.setTotalImages(1);
        task.setDispatchId("dispatch-defect");

        java.util.Map<String, Object> bbox = new java.util.LinkedHashMap<>();
        bbox.put("x", 12);
        bbox.put("y", 18);
        bbox.put("width", 90);
        bbox.put("height", 40);

        java.util.Map<String, Object> defect = new java.util.LinkedHashMap<>();
        defect.put("imageName", "img001.jpg");
        defect.put("sourceKey", "detection/source/img001.jpg");
        defect.put("previewKey", "detection/result/img001.jpg");
        defect.put("defectType", "Rusty");
        defect.put("confidence", 0.92);
        defect.put("area", 3600);
        defect.put("positionRegion", "CENTER");
        defect.put("severityLevel", "MAJOR");
        defect.put("bbox", bbox);

        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);

        fixture.service.applyFinishedEvent(DetectionTaskFinishedEvent.builder()
                .taskId("det_defect")
                .eventId("event-defect")
                .dispatchId("dispatch-defect")
                .status("COMPLETED")
                .resultOssPrefix("detection/task/Result/")
                .resultJsonKey("detection/task/Result/detection_results.json")
                .previewKeys(List.of("detection/result/img001.jpg"))
                .statistics(java.util.Map.of("classCounts", java.util.Map.of("Rusty", 1)))
                .defectEvidence(List.of(defect))
                .totalImages(1)
                .successfulImages(1)
                .failedImages(0)
                .build());

        ArgumentCaptor<DetectionTask> taskCaptor = ArgumentCaptor.forClass(DetectionTask.class);
        verify(fixture.detectionTaskMapper, org.mockito.Mockito.atLeastOnce()).updateById(taskCaptor.capture());
        DetectionTask updatedTask = taskCaptor.getAllValues().get(taskCaptor.getAllValues().size() - 1);

        assertEquals(1, updatedTask.getDefectCount());
        assertEquals("MAJOR", updatedTask.getMaxDefectSeverity());
        assertEquals("Rusty", updatedTask.getPrimaryDefectType());
        assertTrue(updatedTask.getDefectEvidenceJson().contains("\"defectType\":\"Rusty\""));
        assertTrue(updatedTask.getDefectEvidenceJson().contains("\"positionRegion\":\"CENTER\""));
    }

    @Test
    void ignoresFinishedEventFromStaleDispatch() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_stale");
        task.setDispatchId("dispatch-current");
        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);

        fixture.service.applyFinishedEvent(DetectionTaskFinishedEvent.builder()
                .taskId("det_stale")
                .eventId("event-old")
                .dispatchId("dispatch-old")
                .status("COMPLETED")
                .build());

        verify(fixture.detectionTaskMapper, Mockito.never()).updateById(any());
    }

    @Test
    void ignoresDuplicateFinishedEvent() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_duplicate");
        task.setDispatchId("dispatch-current");
        task.setLastFinishedEventId("event-1");
        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);

        fixture.service.applyFinishedEvent(DetectionTaskFinishedEvent.builder()
                .taskId("det_duplicate")
                .eventId("event-1")
                .dispatchId("dispatch-current")
                .status("COMPLETED")
                .build());

        verify(fixture.detectionTaskMapper, Mockito.never()).updateById(any());
    }

    @Test
    void backgroundFailureCanUpdateTaskWithoutUserSecurityContext() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("det_background_failure");
        task.setCreatedBy("alice");
        when(fixture.detectionTaskMapper.selectOne(any())).thenReturn(task);
        SecurityContextHolder.clearContext();

        fixture.service.failTask("det_background_failure", "broker unavailable");

        verify(fixture.detectionTaskMapper).updateById(task);
        assertEquals("FAILED", task.getStatus());
        assertEquals("broker unavailable", task.getErrorMessage());
    }
}
