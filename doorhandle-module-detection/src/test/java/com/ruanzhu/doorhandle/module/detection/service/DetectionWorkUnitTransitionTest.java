package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitSubmitRequest;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionWorkUnit;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionWorkUnitMapper;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionWorkUnitImageMapper;
import com.ruanzhu.doorhandle.module.detection.service.impl.DetectionWorkUnitServiceImpl;
import org.junit.jupiter.api.Test;
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
        var result = new DetectionWorkUnitServiceImpl(mapper, images).submit("WU", request, "A");
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
        var service = new DetectionWorkUnitServiceImpl(mapper, images);
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
        var service = new DetectionWorkUnitServiceImpl(mapper, images);
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
        var service = new DetectionWorkUnitServiceImpl(mapper, mock(DetectionWorkUnitImageMapper.class));
        var result = service.recall("WU", 2, "主管");
        assertNull(result.getAssigneeUserId()); assertEquals(3, result.getVersion());
        verify(mapper, never()).updateById(any());
    }

    @Test void concurrentRecallIsRejected() {
        var mapper = mock(DetectionWorkUnitMapper.class);
        var unit = new DetectionWorkUnit(); unit.setStatus("ASSIGNED"); unit.setVersion(2);
        when(mapper.selectOne(any())).thenReturn(unit);
        var service = new DetectionWorkUnitServiceImpl(mapper, mock(DetectionWorkUnitImageMapper.class));
        assertEquals(409, assertThrows(BusinessException.class, () -> service.recall("WU", 2, "主管")).getCode());
    }
}
