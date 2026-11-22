package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitApplyRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitDecisionRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitSubmitRequest;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionWorkUnit;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionWorkUnitMapper;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionWorkUnitImageMapper;
import com.ruanzhu.doorhandle.module.detection.service.impl.DetectionWorkUnitServiceImpl;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import static org.mockito.Mockito.*;
import static org.junit.jupiter.api.Assertions.*;

class DetectionWorkUnitTransitionTest {
    @Test void submissionCountsPersistedResultsInsteadOfClientValue() {
        var mapper = mock(DetectionWorkUnitMapper.class);
        var images = mock(DetectionWorkUnitImageMapper.class);
        var unit = new DetectionWorkUnit();
        unit.setWorkUnitId("WU"); unit.setAssigneeUserId("A");
        unit.setStatus("PROCESSING"); unit.setVersion(2); unit.setImageCount(2);
        var success = new com.ruanzhu.doorhandle.module.detection.entity.DetectionWorkUnitImage();
        success.setStatus("SUCCESS");
        var failed = new com.ruanzhu.doorhandle.module.detection.entity.DetectionWorkUnitImage();
        failed.setStatus("FAILED");
        when(mapper.selectOne(any())).thenReturn(unit);
        when(images.findByWorkUnitId("WU")).thenReturn(java.util.List.of(success, failed));
        when(mapper.transition(any(), eq(2), eq("PROCESSING"))).thenReturn(1);
        var request = new DetectionWorkUnitSubmitRequest();
        request.setExpectedVersion(2); request.setCompletedCount(5000);
        var result = new DetectionWorkUnitServiceImpl(mapper, images, mock(BusinessUserDirectory.class), mock(DetectionWorkUnitAudit.class)).submit("WU", request, "A");
        assertEquals(1, result.getCompletedCount());
        assertEquals("SUBMITTED", result.getStatus());
        assertEquals(3, result.getVersion());
        assertNotNull(result.getSubmittedAt());
    }

    @Test void pendingImagePreventsSubmission() {
        var mapper = mock(DetectionWorkUnitMapper.class);
        var images = mock(DetectionWorkUnitImageMapper.class);
        var unit = new DetectionWorkUnit();
        unit.setAssigneeUserId("A"); unit.setStatus("ASSIGNED");
        unit.setVersion(2); unit.setImageCount(1);
        var pending = new com.ruanzhu.doorhandle.module.detection.entity.DetectionWorkUnitImage();
        pending.setStatus("PENDING");
        when(mapper.selectOne(any())).thenReturn(unit);
        when(images.findByWorkUnitId("WU")).thenReturn(java.util.List.of(pending));
        var request = new DetectionWorkUnitSubmitRequest(); request.setExpectedVersion(2);
        var service = new DetectionWorkUnitServiceImpl(mapper, images, mock(BusinessUserDirectory.class), mock(DetectionWorkUnitAudit.class));
        assertEquals(409, assertThrows(BusinessException.class,
                () -> service.submit("WU", request, "A")).getCode());
        verify(mapper, never()).transition(any(), any(), any());
    }

    @Test void applicantCannotSubmitAfterReassignment() {
        var mapper = mock(DetectionWorkUnitMapper.class);
        var images = mock(DetectionWorkUnitImageMapper.class);
        var unit = new DetectionWorkUnit();
        unit.setApplicantUserId("A"); unit.setAssigneeUserId("B"); unit.setStatus("ASSIGNED");
        when(mapper.selectOne(any())).thenReturn(unit);
        var service = new DetectionWorkUnitServiceImpl(mapper, images, mock(BusinessUserDirectory.class), mock(DetectionWorkUnitAudit.class));
        var error = assertThrows(BusinessException.class, () -> service.submit("WU", new DetectionWorkUnitSubmitRequest(), "A"));
        assertEquals(403, error.getCode());
        verifyNoInteractions(images);
    }

    @Test void recallClearsAssigneeAndUsesConditionalWrite() {
        var mapper = mock(DetectionWorkUnitMapper.class);
        var unit = new DetectionWorkUnit();
        unit.setWorkUnitId("WU"); unit.setAssigneeUserId("B"); unit.setVersion(2); unit.setStatus("ASSIGNED");
        when(mapper.selectOne(any())).thenReturn(unit);
        when(mapper.transition(any(), eq(2), eq("ASSIGNED"))).thenReturn(1);
        var service = new DetectionWorkUnitServiceImpl(mapper, mock(DetectionWorkUnitImageMapper.class), mock(BusinessUserDirectory.class), mock(DetectionWorkUnitAudit.class));
        var result = service.recall("WU", 2, "主管");
        assertNull(result.getAssigneeUserId()); assertEquals(3, result.getVersion());
        verify(mapper, never()).updateById(any());
    }

    @Test void concurrentRecallIsRejected() {
        var mapper = mock(DetectionWorkUnitMapper.class);
        var unit = new DetectionWorkUnit(); unit.setStatus("ASSIGNED"); unit.setVersion(2);
        when(mapper.selectOne(any())).thenReturn(unit);
        var service = new DetectionWorkUnitServiceImpl(mapper, mock(DetectionWorkUnitImageMapper.class), mock(BusinessUserDirectory.class), mock(DetectionWorkUnitAudit.class));
        assertEquals(409, assertThrows(BusinessException.class, () -> service.recall("WU", 2, "主管")).getCode());
    }

    @Test void applyRetriesReturnTheExistingApplicationAndRejectChangedInput() {
        var mapper = mock(DetectionWorkUnitMapper.class);
        var users = mock(BusinessUserDirectory.class);
        when(users.authenticated()).thenReturn(new BusinessUserDirectory.Identity(7, "DET-0001", false));
        var service = new DetectionWorkUnitServiceImpl(mapper, mock(DetectionWorkUnitImageMapper.class), users, mock(DetectionWorkUnitAudit.class));
        var request = new DetectionWorkUnitApplyRequest();
        request.setRequestId(UUID.randomUUID());
        request.setImageCount(2);
        var stored = new DetectionWorkUnit();
        stored.setApplicantUserId("DET-0001");
        stored.setImageCount(2);
        stored.setStrategy("UNDETECTED_ONLY");
        stored.setBatchId("det_folder_0123456789abcdef0123456789abcdef");
        when(mapper.lock(anyString())).thenReturn(stored);

        assertSame(stored, service.apply(request));
        assertSame(stored, service.apply(request));
        var applications = ArgumentCaptor.forClass(DetectionWorkUnit.class);
        verify(mapper, times(2)).insertApplication(applications.capture());
        assertEquals(applications.getAllValues().get(0).getWorkUnitId(), applications.getValue().getWorkUnitId());
        verify(users, times(2)).lockDetectionEmployee(7, "DET-0001");

        request.setImageCount(3);
        assertEquals(409, assertThrows(BusinessException.class, () -> service.apply(request)).getCode());
    }

    @Test void legacyRecallCannotDetachAnApplicationFromItsFolderTask() {
        var mapper = mock(DetectionWorkUnitMapper.class);
        var unit = new DetectionWorkUnit();
        unit.setStatus("ASSIGNED");
        unit.setVersion(2);
        unit.setBatchId("det_folder_0123456789abcdef0123456789abcdef");
        when(mapper.selectOne(any())).thenReturn(unit);
        var service = new DetectionWorkUnitServiceImpl(mapper, mock(DetectionWorkUnitImageMapper.class), mock(BusinessUserDirectory.class), mock(DetectionWorkUnitAudit.class));

        assertEquals(409, assertThrows(BusinessException.class, () -> service.recall("WU", 2, "主管")).getCode());
        verify(mapper, never()).transition(any(), any(), any());
    }

    @Test void supervisorCannotApplyOrWithdrawAndEmployeeCannotReject() {
        var mapper = mock(DetectionWorkUnitMapper.class);
        var users = mock(BusinessUserDirectory.class);
        var service = new DetectionWorkUnitServiceImpl(mapper, mock(DetectionWorkUnitImageMapper.class), users, mock(DetectionWorkUnitAudit.class));
        var command = new DetectionWorkUnitDecisionRequest(0, UUID.randomUUID(), "资料需要补充");
        when(users.authenticated()).thenReturn(new BusinessUserDirectory.Identity(3, "SUP-0001", true));
        assertEquals(403, assertThrows(BusinessException.class,
                () -> service.apply(new DetectionWorkUnitApplyRequest())).getCode());
        assertEquals(403, assertThrows(BusinessException.class, () -> service.withdraw("WU", command)).getCode());
        when(users.authenticated()).thenReturn(new BusinessUserDirectory.Identity(7, "DET-0001", false));
        assertEquals(403, assertThrows(BusinessException.class, () -> service.reject("WU", command)).getCode());
        verifyNoInteractions(mapper);
    }

    @Test void applicantCanWithdrawOnceAndCannotWithdrawSomeoneElsesApplication() {
        var mapper = mock(DetectionWorkUnitMapper.class);
        var users = mock(BusinessUserDirectory.class);
        var audit = mock(DetectionWorkUnitAudit.class);
        var service = new DetectionWorkUnitServiceImpl(mapper, mock(DetectionWorkUnitImageMapper.class), users, audit);
        var unit = waitingApplication();
        var command = new DetectionWorkUnitDecisionRequest(0, UUID.randomUUID(), null);
        when(mapper.lock("WU")).thenReturn(unit);
        when(users.authenticated()).thenReturn(new BusinessUserDirectory.Identity(8, "DET-0002", false));
        assertEquals(403, assertThrows(BusinessException.class, () -> service.withdraw("WU", command)).getCode());
        verify(mapper, never()).recordApplicationDecision(any(), anyInt());

        when(users.authenticated()).thenReturn(new BusinessUserDirectory.Identity(7, "DET-0001", false));
        when(mapper.recordApplicationDecision(unit, 0)).thenReturn(1);
        assertEquals("WITHDRAWN", service.withdraw("WU", command).getStatus());
        assertEquals(1, unit.getVersion());
        assertSame(unit, service.withdraw("WU", command));
        assertEquals("原申请备注", unit.getRemark());
        verify(users, times(2)).lockDetectionEmployee(7, "DET-0001");
        verify(mapper).recordApplicationDecision(unit, 0);
        verify(audit).record(new BusinessUserDirectory.Identity(7, "DET-0001", false),
                "DETECTION_APPLICATION_WITHDRAWN", "WU", command.requestId().toString(), 1L);
    }

    @Test void rejectionIsVersionedAndKeepsOriginalApplicationAndDecisionReason() {
        var mapper = mock(DetectionWorkUnitMapper.class);
        var users = mock(BusinessUserDirectory.class);
        var service = new DetectionWorkUnitServiceImpl(mapper, mock(DetectionWorkUnitImageMapper.class), users, mock(DetectionWorkUnitAudit.class));
        var unit = waitingApplication();
        var supervisor = new BusinessUserDirectory.Identity(3, "SUP-0001", true);
        when(users.authenticated()).thenReturn(supervisor);
        when(users.lockCurrent(3, "SUP-0001")).thenReturn(supervisor);
        when(mapper.lock("WU")).thenReturn(unit);
        when(mapper.recordApplicationDecision(unit, 0)).thenReturn(1);

        var requestId = UUID.randomUUID();
        assertEquals(400, assertThrows(BusinessException.class, () -> service.reject("WU",
                new DetectionWorkUnitDecisionRequest(0, requestId, " "))).getCode());
        assertEquals(409, assertThrows(BusinessException.class, () -> service.reject("WU",
                new DetectionWorkUnitDecisionRequest(1, requestId, "请补充采集信息"))).getCode());
        var command = new DetectionWorkUnitDecisionRequest(0, requestId, "  请补充采集信息  ");
        assertEquals("REJECTED", service.reject("WU", command).getStatus());
        assertEquals(1, unit.getVersion());
        assertEquals("原申请备注", unit.getRemark());
        assertEquals("请补充采集信息", unit.getDecisionReason());
        assertSame(unit, service.reject("WU", command));
        assertEquals(409, assertThrows(BusinessException.class, () -> service.reject("WU",
                new DetectionWorkUnitDecisionRequest(0, requestId, "请补充设备编号"))).getCode());
        verify(mapper).recordApplicationDecision(unit, 0);
    }

    @Test void assignedOrAlreadyDecidedApplicationsCannotBeClosedByANewCommand() {
        var mapper = mock(DetectionWorkUnitMapper.class);
        var users = mock(BusinessUserDirectory.class);
        var service = new DetectionWorkUnitServiceImpl(mapper, mock(DetectionWorkUnitImageMapper.class), users, mock(DetectionWorkUnitAudit.class));
        var unit = waitingApplication();
        when(mapper.lock("WU")).thenReturn(unit);
        when(users.authenticated()).thenReturn(new BusinessUserDirectory.Identity(7, "DET-0001", false));
        var command = new DetectionWorkUnitDecisionRequest(0, UUID.randomUUID(), null);
        for (String status : java.util.List.of("ASSIGNED", "PROCESSING", "SUBMITTED", "REJECTED", "WITHDRAWN")) {
            unit.setStatus(status);
            assertEquals(409, assertThrows(BusinessException.class, () -> service.withdraw("WU", command)).getCode());
        }
        verify(mapper, never()).recordApplicationDecision(any(), anyInt());
    }

    private static DetectionWorkUnit waitingApplication() {
        var unit = new DetectionWorkUnit();
        unit.setWorkUnitId("WU");
        unit.setApplicantUserId("DET-0001");
        unit.setStatus("WAITING");
        unit.setVersion(0);
        unit.setRemark("原申请备注");
        return unit;
    }
}
