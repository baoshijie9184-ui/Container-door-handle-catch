package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DuplicateTicketResolveRequest;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionDuplicateTicket;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionDuplicateTicketMapper;
import com.ruanzhu.doorhandle.module.detection.service.impl.DetectionDuplicateTicketServiceImpl;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class DetectionDuplicateResolutionTest {
    @Test void concurrentChangeMustRejectSave() {
        var mapper = mock(DetectionDuplicateTicketMapper.class);
        var ticket = new DetectionDuplicateTicket();
        ticket.setTicketId("T1"); ticket.setVersion(0); ticket.setStatus("OPEN");
        when(mapper.selectOne(any())).thenReturn(ticket);
        when(mapper.resolveIfVersion(any(), eq(0))).thenReturn(0);
        var req = new DuplicateTicketResolveRequest();
        req.setExpectedVersion(0); req.setResolution("ACCEPT_LEFT");
        var service = new DetectionDuplicateTicketServiceImpl(mapper);
        var error = assertThrows(BusinessException.class, () -> service.resolve("T1", req, "supervisor-a"));
        assertEquals(409, error.getCode());
        verify(mapper, never()).updateById(any());
    }

    @Test void unsupportedConclusionMustNotTouchDatabase() {
        var mapper = mock(DetectionDuplicateTicketMapper.class);
        var req = new DuplicateTicketResolveRequest();
        req.setExpectedVersion(0); req.setResolution("DELETE_ALL");
        assertThrows(BusinessException.class, () -> new DetectionDuplicateTicketServiceImpl(mapper).resolve("T1", req, "supervisor-a"));
        verifyNoInteractions(mapper);
    }
}
