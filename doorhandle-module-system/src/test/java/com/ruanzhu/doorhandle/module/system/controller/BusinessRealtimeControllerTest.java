package com.ruanzhu.doorhandle.module.system.controller;

import com.ruanzhu.doorhandle.module.system.realtime.BusinessRealtimeService;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import java.time.Instant;
import java.util.List;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class BusinessRealtimeControllerTest {
    final BusinessRealtimeService service=mock(BusinessRealtimeService.class);
    final MockEnvironment environment=new MockEnvironment().withProperty("collaboration.sessions.enabled","true")
            .withProperty("collaboration.change-history.enabled","true").withProperty("operations.audit.enabled","true");
    final BusinessRealtimeController controller=new BusinessRealtimeController(service,environment);
    final TenantPrincipal principal=new TenantPrincipal(7L,"alice","",List.of(),"a".repeat(64),"page-context");
    MockHttpServletRequest request(){var request=new MockHttpServletRequest("GET","/api/realtime/changes");request.setScheme("https");request.setServerName("factory.example");request.setServerPort(8443);return request;}
    static void status(Runnable operation,int expected){assertThatThrownBy(operation::run).isInstanceOf(ResponseStatusException.class).satisfies(f->assertThat(((ResponseStatusException)f).getStatusCode().value()).isEqualTo(expected));}
    @Test void trustedAccessExpiryAndSessionContextReachTheServiceAndDisableProxyBuffering(){
        var request=request();request.addHeader("Origin","https://factory.example:8443");Instant expiry=Instant.now().plusSeconds(30);request.setAttribute("doorhandle.auth.accessExpiresAt",expiry);
        var emitter=new SseEmitter();when(service.open(7,"alice","a".repeat(64),"page-context",expiry)).thenReturn(emitter);
        var response=controller.changes(principal,request);assertThat(response.getBody()).isSameAs(emitter);assertThat(response.getHeaders().getFirst("X-Accel-Buffering")).isEqualTo("no");assertThat(response.getHeaders().getFirst("Cache-Control")).contains("no-store","no-transform");
    }
    @ParameterizedTest @ValueSource(strings={"https://factory.example","http://factory.example:8443","https://attacker.example:8443","https://user@factory.example:8443","null"})
    void mismatchedOriginHostProtocolPortOrUserinfoAreRejected(String source){var request=request();request.addHeader("Origin",source);status(()->BusinessRealtimeController.sameOrigin(request),403);}
    @Test void sameOriginRefererAndOmittedHeadersAreAllowedButCrossSiteFetchIsRejected(){
        var request=request();request.addHeader("Referer","https://factory.example:8443/workbench");BusinessRealtimeController.sameOrigin(request);
        BusinessRealtimeController.sameOrigin(request());var cross=request();cross.addHeader("Sec-Fetch-Site","cross-site");status(()->BusinessRealtimeController.sameOrigin(cross),403);
    }
    @ParameterizedTest @ValueSource(strings={"collaboration.sessions.enabled","collaboration.change-history.enabled","operations.audit.enabled"})
    void everyBackendPrerequisiteGateIsRequired(String key){environment.setProperty(key,"false");status(()->controller.changes(principal,request()),503);verifyNoInteractions(service);}
    @Test void missingDisabledOrUntrackedIdentityAndUntrustedExpiryAreRejected(){
        status(()->controller.changes(null,request()),401);
        status(()->controller.changes(new TenantPrincipal(7L,"alice","",List.of(),null,"page-context"),request()),401);
        status(()->controller.changes(new TenantPrincipal(7L,"alice","",List.of(),"a".repeat(64),"page-context",false),request()),401);
        status(()->controller.changes(principal,request()),401);
        var untrusted=request();untrusted.setAttribute("doorhandle.auth.accessExpiresAt","2099-01-01");status(()->controller.changes(principal,untrusted),401);verifyNoInteractions(service);
    }
}
