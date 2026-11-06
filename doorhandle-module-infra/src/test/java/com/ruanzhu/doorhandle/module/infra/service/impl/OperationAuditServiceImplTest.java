package com.ruanzhu.doorhandle.module.infra.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.infra.entity.OperationAuditLog;
import com.ruanzhu.doorhandle.module.infra.service.InfraOperationAuditStore;
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
        InfraOperationAuditStore mapper = mock(InfraOperationAuditStore.class);
        OperationAuditServiceImpl service = new OperationAuditServiceImpl(mapper, new ObjectMapper());
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken("bob", "n/a"));

        service.recordSuccess("MODEL", "12", "PUBLISH",
                Map.of("token", "secret", "status", "PUBLISHED"));

        ArgumentCaptor<OperationAuditLog> captor = ArgumentCaptor.forClass(OperationAuditLog.class);
        verify(mapper).append(captor.capture());
        assertThat(captor.getValue().getOperator()).isEqualTo("bob");
        assertThat(captor.getValue().getResult()).isEqualTo("SUCCESS");
        assertThat(captor.getValue().getChangeSummary())
                .contains("PUBLISHED", "[REDACTED]")
                .doesNotContain("secret");
    }

    @Test void failedHttpRequestKeepsItsRequestSnapshotStatusAndErrorClass() throws Exception {
        var store=mock(InfraOperationAuditStore.class);var json=new ObjectMapper();
        var service=new OperationAuditServiceImpl(store,json);
        service.recordHttp("DELETE","/api/models/12",409,"127.0.0.1",new IllegalArgumentException("private diagnostic"));
        var captured=ArgumentCaptor.forClass(OperationAuditLog.class);verify(store).append(captured.capture());
        var row=captured.getValue();var summary=json.readTree(row.getChangeSummary());
        assertThat(row.getResult()).isEqualTo("FAILURE");assertThat(row.getRequestMethod()).isEqualTo("DELETE");
        assertThat(row.getRequestPath()).isEqualTo("/api/models/12");assertThat(row.getClientIp()).isEqualTo("127.0.0.1");
        assertThat(summary.path("status").asInt()).isEqualTo(409);assertThat(summary.path("error").asText()).isEqualTo("IllegalArgumentException");
        assertThat(row.getChangeSummary()).doesNotContain("private diagnostic");
    }

    @Test void largeSummaryIsCompleteJsonAndLongRequestPathIsNotTruncatedToTheResourceId() throws Exception {
        var store=mock(InfraOperationAuditStore.class);var json=new ObjectMapper();var service=new OperationAuditServiceImpl(store,json);
        String path="/api/"+"r".repeat(600);
        service.recordHttp("PATCH",path,500,"::1",null);
        service.recordSuccess("MODEL","12","PUBLISH",Map.of("note","n".repeat(9000)));
        var captured=ArgumentCaptor.forClass(OperationAuditLog.class);org.mockito.Mockito.verify(store,org.mockito.Mockito.times(2)).append(captured.capture());
        var http=captured.getAllValues().get(0);assertThat(http.getResourceId()).isNull();assertThat(http.getRequestPath()).isEqualTo(path);
        assertThat(json.readTree(http.getChangeSummary()).path("status").asInt()).isEqualTo(500);
        assertThat(json.readTree(captured.getAllValues().get(1).getChangeSummary()).path("note").asText()).hasSize(9000);
    }
}
