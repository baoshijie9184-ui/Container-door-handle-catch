package com.ruanzhu.doorhandle.module.infra.security;

import com.ruanzhu.doorhandle.module.infra.service.OperationAuditService;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.mockito.ArgumentMatchers.isNull;
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

        verify(auditService).recordHttp(eq("POST"),eq("/api/models/12/publish"),eq(200),eq(request.getRemoteAddr()),isNull());
    }

    @Test void failedRequestKeepsStatusAndExceptionAndReadOnlyRequestsAreNotRecorded() {
        OperationAuditService auditService=mock(OperationAuditService.class);
        var interceptor=new OperationAuditInterceptor(auditService);
        var request=new MockHttpServletRequest("DELETE","/api/models/12");var response=new MockHttpServletResponse();response.setStatus(409);
        var failure=new IllegalStateException("conflict");interceptor.afterCompletion(request,response,new Object(),failure);
        verify(auditService).recordHttp("DELETE","/api/models/12",409,request.getRemoteAddr(),failure);
        interceptor.afterCompletion(new MockHttpServletRequest("GET","/api/models/12"),response,new Object(),null);
        org.mockito.Mockito.verifyNoMoreInteractions(auditService);
    }
}
