package com.ruanzhu.doorhandle.module.system.controller;

import com.ruanzhu.doorhandle.module.system.dto.LoginRequest;
import com.ruanzhu.doorhandle.module.system.dto.LoginResponse;
import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.system.security.LoginRateLimiter;
import com.ruanzhu.doorhandle.module.system.service.AuthService;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AuthControllerTest {

    @Test
    void checkAuthAdvertisesOptionalBusinessFeaturesIndependently() {
        AuthController controller = new AuthController(mock(AuthService.class), mock(LoginRateLimiter.class),
                mock(com.ruanzhu.doorhandle.module.system.service.AccountIdentityService.class));
        ReflectionTestUtils.setField(controller, "qualityDigests", true);
        ReflectionTestUtils.setField(controller, "reportEventDelivery", true);
        var context = SecurityContextHolder.createEmptyContext();
        context.setAuthentication(new UsernamePasswordAuthenticationToken("alice", null,
                List.of(new SimpleGrantedAuthority("ROLE_SUPERVISOR"))));
        SecurityContextHolder.setContext(context);
        try {
            var capabilities = (Map<?, ?>) controller.checkAuth().getData().get("capabilities");
            assertThat(capabilities.get("qualityDigests")).isEqualTo(true);
            assertThat(capabilities.get("detectionIdentity")).isEqualTo(false);
            assertThat(capabilities.get("agentModelConfig")).isEqualTo(false);
            assertThat(capabilities.get("reportEventDelivery")).isEqualTo(true);
        } finally {
            SecurityContextHolder.clearContext();
        }
    }

    @Test
    void loginSetsHttpOnlyJwtCookieForAuthenticatedFileRequests() {
        AuthService authService = mock(AuthService.class);
        LoginRateLimiter loginRateLimiter = mock(LoginRateLimiter.class);
        AuthController controller = new AuthController(authService, loginRateLimiter, mock(com.ruanzhu.doorhandle.module.system.service.AccountIdentityService.class));
        ReflectionTestUtils.setField(controller, "jwtExpirationSeconds", 86400L);
        ReflectionTestUtils.setField(controller, "cookieSecure", false);
        LoginRequest request = new LoginRequest();
        request.setUsername("alice");
        request.setPassword("secret");
        LoginResponse loginResponse = new LoginResponse();
        loginResponse.setToken("jwt-token");
        loginResponse.setUsername("alice");
        when(loginRateLimiter.isAllowed("127.0.0.1")).thenReturn(true);
        when(authService.login(request)).thenReturn(loginResponse);

        ResponseEntity<?> response = controller.login(request, new MockHttpServletRequest(), new MockHttpServletResponse());

        String setCookie = response.getHeaders().getFirst(HttpHeaders.SET_COOKIE);
        assertThat(setCookie).contains("DOOR_HANDLE_TOKEN=jwt-token");
        assertThat(setCookie).contains("HttpOnly");
        assertThat(setCookie).contains("SameSite=Lax");
        Result<?> body = (Result<?>) response.getBody();
        LoginResponse responseBody = (LoginResponse) body.getData();
        assertThat(responseBody.getToken()).isNull();
    }

    @Test
    void loginCanMarkJwtCookieSecureForHttpsDeployments() {
        AuthService authService = mock(AuthService.class);
        LoginRateLimiter loginRateLimiter = mock(LoginRateLimiter.class);
        AuthController controller = new AuthController(authService, loginRateLimiter, mock(com.ruanzhu.doorhandle.module.system.service.AccountIdentityService.class));
        ReflectionTestUtils.setField(controller, "jwtExpirationSeconds", 86400L);
        ReflectionTestUtils.setField(controller, "cookieSecure", true);
        LoginRequest request = new LoginRequest();
        request.setUsername("alice");
        request.setPassword("secret");
        LoginResponse loginResponse = new LoginResponse();
        loginResponse.setToken("jwt-token");
        loginResponse.setUsername("alice");
        when(loginRateLimiter.isAllowed("127.0.0.1")).thenReturn(true);
        when(authService.login(request)).thenReturn(loginResponse);

        ResponseEntity<?> response = controller.login(request, new MockHttpServletRequest(), new MockHttpServletResponse());

        assertThat(response.getHeaders().getFirst(HttpHeaders.SET_COOKIE)).contains("Secure");
    }
}
