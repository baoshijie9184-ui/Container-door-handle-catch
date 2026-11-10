package com.ruanzhu.doorhandle.module.detection.controller;
import com.ruanzhu.doorhandle.module.detection.service.QualityReportService;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.method.annotation.AuthenticationPrincipalArgumentResolver;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import java.util.List;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
class QualityReportControllerTest {
    @BeforeEach void authenticateSupervisor() {
        var roles=List.of(new SimpleGrantedAuthority("ROLE_SUPERVISOR"));
        var context=SecurityContextHolder.createEmptyContext();
        context.setAuthentication(new UsernamePasswordAuthenticationToken(
                new TenantPrincipal(3L,"report-supervisor","",roles),null,roles));
        SecurityContextHolder.setContext(context);
    }
    @AfterEach void clearAuthentication(){SecurityContextHolder.clearContext();}
    @Test void retryRequiresMarkerAndExplicitConfirmationBeforeBusinessCall()throws Exception{
        var service=mock(QualityReportService.class);var mvc=MockMvcBuilders.standaloneSetup(new QualityReportController(service)).setCustomArgumentResolvers(new AuthenticationPrincipalArgumentResolver()).setControllerAdvice(new QualityReportExceptionHandler()).build();
        String path="/api/detection/reports/qr-00000000-0000-0000-0000-000000000000/events/00000000-0000-0000-0000-000000000000/retry";
        mvc.perform(post(path).header("X-Report-Action","update").contentType(MediaType.APPLICATION_JSON).content("{\"expectedAttempts\":1,\"confirmed\":false,\"requestId\":\"retry-request\"}")).andExpect(status().isBadRequest());
        mvc.perform(post(path).contentType(MediaType.APPLICATION_JSON).content("{\"expectedAttempts\":1,\"confirmed\":true,\"requestId\":\"retry-request\"}")).andExpect(status().isBadRequest());verifyNoInteractions(service);
    }
    @Test void missingMarkerAndInvalidCommandAre400WithoutCallingBusinessService() throws Exception {
        var service=mock(QualityReportService.class);var mvc=MockMvcBuilders.standaloneSetup(new QualityReportController(service)).setCustomArgumentResolvers(new AuthenticationPrincipalArgumentResolver()).setControllerAdvice(new QualityReportExceptionHandler()).build();
        mvc.perform(post("/api/detection/reports/qr-00000000-0000-0000-0000-000000000000/submit").contentType(MediaType.APPLICATION_JSON)
                .content("{\"expectedVersion\":1,\"requestId\":\"request-123\"}")).andExpect(status().isBadRequest());
        mvc.perform(post("/api/detection/reports").header("X-Report-Action","update").contentType(MediaType.APPLICATION_JSON)
                .content("{\"taskId\":\"../escape\",\"title\":\"标题\",\"narrative\":\"意见\",\"requestId\":\"request-123\"}"))
                .andExpect(status().isBadRequest());
        verifyNoInteractions(service);
    }
}
