package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.module.detection.mapper.DetectionWorkUnitMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.access.AccessDeniedException;
import java.util.List;
import java.util.Map;
import static org.mockito.Mockito.*;
import static org.junit.jupiter.api.Assertions.*;

class DetectionWorkloadDashboardServiceTest {
    private final DetectionWorkUnitMapper mapper = mock(DetectionWorkUnitMapper.class);
    private final com.ruanzhu.doorhandle.module.detection.mapper.DetectionDuplicateTicketMapper duplicateMapper =
            mock(com.ruanzhu.doorhandle.module.detection.mapper.DetectionDuplicateTicketMapper.class);
    private final DetectionWorkloadDashboardService service = new DetectionWorkloadDashboardService(mapper, duplicateMapper);

    @Test void duplicateCountsAreAssignedOnlyAndExcludeResolvedTickets() {
        login("alice", "ROLE_INSPECTOR");
        when(duplicateMapper.countAssignedStatuses("alice")).thenReturn(List.of(
                Map.of("status", "ASSIGNED", "total", 3L), Map.of("status", "RESOLVED", "total", 7L)));
        var result = service.duplicateSummary();
        assertEquals("MINE", result.get("scope"));
        assertEquals(3L, result.get("activeCount"));
        verify(duplicateMapper, never()).countDepartmentStatuses();
        verifyNoInteractions(mapper);
    }

    @Test void duplicateSupervisorSummaryIncludesPendingApproval() {
        login("manager", "ROLE_SUPERVISOR");
        when(duplicateMapper.countDepartmentStatuses()).thenReturn(List.of(
                Map.of("status", "PENDING_APPROVAL", "total", 4L)));
        assertEquals(4L, service.duplicateSummary().get("activeCount"));
        verify(duplicateMapper, never()).countAssignedStatuses(anyString());
    }

    @Test void anonymousDuplicateSummaryIsRejected() {
        assertThrows(AccessDeniedException.class, service::duplicateSummary);
        verifyNoInteractions(duplicateMapper, mapper);
    }

    @AfterEach void clear() { SecurityContextHolder.clearContext(); }

    private void login(String name, String role) {
        SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken(
                name, "unused", List.of(new SimpleGrantedAuthority(role))));
    }

    @Test void inspectorOnlyQueriesAuthenticatedAssignee() {
        login("alice", "ROLE_INSPECTOR");
        when(mapper.countAssignedStatuses("alice")).thenReturn(List.of(Map.of("status", "ASSIGNED", "total", 2L)));
        var result = service.summary();
        assertEquals("MINE", result.get("scope"));
        assertEquals(2L, result.get("activeCount"));
        verify(mapper, never()).countDepartmentStatuses();
    }

    @Test void supervisorCanSeeDepartmentAndEmptyCountsAreZero() {
        login("manager", "ROLE_SUPERVISOR");
        when(mapper.countDepartmentStatuses()).thenReturn(List.of());
        var result = service.summary();
        assertEquals("DEPARTMENT", result.get("scope"));
        assertEquals(0L, result.get("activeCount"));
        verify(mapper, never()).countAssignedStatuses(anyString());
    }

    @Test void unsupportedRoleCannotQueryDatabase() {
        login("guest", "ROLE_GUEST");
        assertThrows(AccessDeniedException.class, service::summary);
        verifyNoInteractions(mapper);
    }

    @Test void unauthenticatedCannotQueryDatabase() {
        assertThrows(AccessDeniedException.class, service::summary);
        verifyNoInteractions(mapper);
    }
}
