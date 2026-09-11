package com.ruanzhu.doorhandle.module.infra.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.infra.entity.OperationAuditLog;
import com.ruanzhu.doorhandle.module.infra.mapper.OperationAuditLogMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

class OperationAuditServiceImplTest {

    @AfterEach
    void clearContext() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void recordsAuthenticatedActorAndRedactsSecretFields() {
        OperationAuditLogMapper mapper = mock(OperationAuditLogMapper.class);
        OperationAuditServiceImpl service = new OperationAuditServiceImpl(mapper, new ObjectMapper());
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken("bob", "n/a"));

        service.recordSuccess("MODEL", "12", "PUBLISH",
                Map.of("token", "secret", "status", "PUBLISHED"));

        ArgumentCaptor<OperationAuditLog> captor = ArgumentCaptor.forClass(OperationAuditLog.class);
        verify(mapper).insert(captor.capture());
        assertThat(captor.getValue().getOperator()).isEqualTo("bob");
        assertThat(captor.getValue().getResult()).isEqualTo("SUCCESS");
        assertThat(captor.getValue().getChangeSummary())
                .contains("PUBLISHED", "[REDACTED]")
                .doesNotContain("secret");
    }
}
