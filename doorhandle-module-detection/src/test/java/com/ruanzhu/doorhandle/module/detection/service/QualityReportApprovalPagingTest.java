package com.ruanzhu.doorhandle.module.detection.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.repository.QualityReportRepository;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.*;

class QualityReportApprovalPagingTest {
    @Test void approvalQueueExcludesSelfBeforePagingAndUsesSameFilterForCount() {
        var actor = new BusinessUserDirectory.Identity(9, "supervisor", true);
        var repository = mock(QualityReportRepository.class);
        when(repository.jdbc()).thenReturn(mock(JdbcTemplate.class));
        var service = new QualityReportService(repository, mock(DetectionTaskMapper.class),
                (id, username) -> new BusinessUserDirectory.Identity(id, username, id == 9),
                mock(DetectionTaskAccessPolicy.class), new ObjectMapper());
        var where = "r.owner_user_id<>:owner AND r.status=:status";
        var filters = Map.of("owner", 9L, "username", "supervisor", "status", "SUBMITTED");
        when(repository.list(where, filters, 1, 5)).thenReturn(List.of());
        when(repository.count(where, filters)).thenReturn(7L);

        assertEquals(7L, service.list(actor, 1, 5, null, null, true).get("total"));
        verify(repository).list(where, filters, 1, 5);
        verify(repository).count(where, filters);
        assertThrows(SecurityException.class, () -> service.list(
                new BusinessUserDirectory.Identity(7, "inspector", false), 1, 5, null, null, true));
    }
}
