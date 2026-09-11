package com.ruanzhu.doorhandle.module.infra.security;

import com.ruanzhu.doorhandle.module.infra.service.OperationAuditService;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

class OperationAuditInterceptorTest {

    @Test
    void auditsSuccessfulMutatingApiRequestWithoutReadingBody() throws Exception {
        OperationAuditService auditService = mock(OperationAuditService.class);
        OperationAuditInterceptor interceptor = new OperationAuditInterceptor(auditService);
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/models/12/publish");
        MockHttpServletResponse response = new MockHttpServletResponse();
        response.setStatus(200);

        interceptor.afterCompletion(request, response, new Object(), null);

        verify(auditService).recordSuccess(eq("API"), eq("/api/models/12/publish"), eq("POST"), anyMap());
    }
}
