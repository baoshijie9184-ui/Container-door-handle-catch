package com.ruanzhu.doorhandle.module.system.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.security.LoginSessionAccess;
import com.ruanzhu.doorhandle.module.system.service.LoginSessionService;
import com.ruanzhu.doorhandle.module.system.util.JwtUtil;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.*;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.core.userdetails.UserDetailsService;
import java.time.Instant;
import java.util.List;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** HTTP credential and page-context boundaries. Executed only by the ECS source test stage. */
class LoginSessionFilterTest {
    final JwtUtil jwt=mock(JwtUtil.class);
    final UserDetailsService users=mock(UserDetailsService.class);
    final LoginSessionService sessions=mock(LoginSessionService.class);
    final JwtAuthenticationFilter filter=new JwtAuthenticationFilter(jwt,users,new ObjectMapper(),sessions);
    final String sid="s".repeat(43),context="c".repeat(43);
    final Instant accessExpiry=Instant.now().plusSeconds(300);
    @AfterEach void clear(){SecurityContextHolder.clearContext();}
    void authenticated(boolean tracking){
        when(sessions.enabled()).thenReturn(tracking);
        when(jwt.getUsernameFromToken("access")).thenReturn("alice");when(jwt.getUserIdFromToken("access")).thenReturn(42L);
        when(jwt.validateToken("access")).thenReturn(true);when(jwt.isAccessToken("access")).thenReturn(true);
        when(jwt.getSessionId("access")).thenReturn(sid);when(jwt.getExpiresAt("access")).thenReturn(accessExpiry);
        when(sessions.requireActive(42L,"alice",LoginSessionService.digest(sid))).thenReturn(
                new LoginSessionAccess.Session(42,"alice","INSPECTOR",LoginSessionService.digest(sid),context,Instant.now().plusSeconds(86400)));
        when(users.loadUserByUsername("alice")).thenReturn(new TenantPrincipal(42L,"alice","hash",List.of(new SimpleGrantedAuthority("ROLE_INSPECTOR"))));
    }
    MockHttpServletRequest request(String method){
        var request=new MockHttpServletRequest(method,"/api/quality/review");request.setServletPath("/api/quality/review");
        request.setCookies(new Cookie("DOOR_HANDLE_TOKEN","access"));return request;
    }
    MockHttpServletResponse call(MockHttpServletRequest request)throws Exception{
        var response=new MockHttpServletResponse();filter.doFilter(request,response,new MockFilterChain());return response;
    }
    @Test void validSessionBindsTrustedDigestContextAndActualAccessExpiry()throws Exception{
        authenticated(true);var request=request("GET");assertThat(call(request).getStatus()).isEqualTo(200);
        var principal=(TenantPrincipal)SecurityContextHolder.getContext().getAuthentication().getPrincipal();
        assertThat(principal.sessionDigest()).isEqualTo(LoginSessionService.digest(sid));assertThat(principal.accountContext()).isEqualTo(context);
        assertThat(request.getAttribute("doorhandle.auth.accessExpiresAt")).isEqualTo(accessExpiry);
    }
    @Test void missingOrStalePageContextCannotWriteThroughANewCookie()throws Exception{
        authenticated(true);for(String supplied:List.of("","old-page")){
            var request=request("POST");request.addHeader("Origin","http://localhost");if(!supplied.isEmpty())request.addHeader("X-Account-Context",supplied);
            var response=call(request);assertThat(response.getStatus()).isEqualTo(409);assertThat(response.getContentAsString()).contains("ACCOUNT_CONTEXT_CHANGED");
        }
    }
    @Test void currentPageContextCanWriteAndSameOriginRefererIsAccepted()throws Exception{
        authenticated(true);var request=request("POST");request.addHeader("Referer","http://localhost/workbench");request.addHeader("X-Account-Context",context);
        assertThat(call(request).getStatus()).isEqualTo(200);
    }
    @Test void crossOriginOrMissingOriginCookieWritesCannotUseASpoofedBearerHeader()throws Exception{
        for(String origin:List.of("","http://attacker.invalid")){
            var request=request("POST");request.addHeader("Authorization","Bearer spoofed");if(!origin.isEmpty())request.addHeader("Origin",origin);
            assertThat(call(request).getStatus()).isEqualTo(403);
        }
        verifyNoInteractions(jwt,users);
    }
    @Test void disabledCurrentAccountReachesSessionRevocationBeforeUserDetailsLoading()throws Exception{
        authenticated(true);when(sessions.requireActive(42L,"alice",LoginSessionService.digest(sid))).thenThrow(new org.springframework.security.authentication.DisabledException("disabled"));
        assertThat(call(request("GET")).getStatus()).isEqualTo(401);verifyNoInteractions(users);
    }
    @Test void refreshCredentialCannotAuthenticateABusinessRead()throws Exception{
        authenticated(true);when(jwt.isAccessToken("access")).thenReturn(false);when(jwt.isRefreshToken("access")).thenReturn(true);
        assertThat(call(request("GET")).getStatus()).isEqualTo(401);verifyNoInteractions(users);
    }
    @Test void legacyModeStillFencesASuppliedOldContextWithoutRequiringANewHeader()throws Exception{
        authenticated(false);var stale=request("POST");stale.addHeader("Origin","http://localhost");stale.addHeader("X-Account-Context","old-page");
        assertThat(call(stale).getStatus()).isEqualTo(409);
        var legacy=request("POST");legacy.addHeader("Origin","http://localhost");assertThat(call(legacy).getStatus()).isEqualTo(200);
        var principal=(TenantPrincipal)SecurityContextHolder.getContext().getAuthentication().getPrincipal();
        assertThat(principal.sessionDigest()).isNull();assertThat(principal.accountContext()).isEqualTo(LoginSessionService.legacyAccountContext(42,"alice"));
    }
}
