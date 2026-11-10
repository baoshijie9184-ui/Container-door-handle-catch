package com.ruanzhu.doorhandle.module.system.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.system.controller.AuthController;
import com.ruanzhu.doorhandle.module.system.dto.*;
import com.ruanzhu.doorhandle.module.system.service.*;
import com.ruanzhu.doorhandle.module.system.util.JwtUtil;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.*;
import org.springframework.http.HttpHeaders;
import org.springframework.mock.web.*;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.test.util.ReflectionTestUtils;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class AuthScopedCookieTest {
    final String context="a".repeat(43);
    final AuthService auth=mock(AuthService.class);
    final LoginRateLimiter limiter=mock(LoginRateLimiter.class);
    AuthController controller(){var props=new LoginSessionProperties();props.setEnabled(true);var controller=new AuthController(auth,limiter,mock(AccountIdentityService.class),props);ReflectionTestUtils.setField(controller,"jwtExpirationSeconds",3600L);ReflectionTestUtils.setField(controller,"refreshExpirationSeconds",86400L);ReflectionTestUtils.setField(controller,"cookieSecure",false);return controller;}
    LoginResponse response(){var response=new LoginResponse();response.setAccountContext(context);response.setToken("access");response.setRefreshToken("refresh");return response;}
    @AfterEach void clear(){SecurityContextHolder.clearContext();}
    @Test void selectorAndCleanupNamesHaveClosedFormats(){
        assertThat(AuthCookieNames.scoped(AuthCookieNames.access(context))).isTrue();assertThat(AuthCookieNames.scoped("DOOR_HANDLE_TOKEN_bad")).isFalse();assertThat(AuthCookieNames.scoped("OTHER_APP_"+context)).isFalse();
        var invalid=new MockHttpServletRequest();invalid.setCookies(new Cookie(AuthCookieNames.SELECTOR,"invalid"));assertThatThrownBy(()->AuthCookieNames.selected(invalid)).isInstanceOf(org.springframework.security.core.AuthenticationException.class);
        var duplicate=new MockHttpServletRequest();duplicate.setCookies(new Cookie(AuthCookieNames.SELECTOR,context),new Cookie(AuthCookieNames.SELECTOR,context));assertThatThrownBy(()->AuthCookieNames.selected(duplicate)).isInstanceOf(org.springframework.security.core.AuthenticationException.class);
    }
    @Test void loginWritesOneSelectorAndOnlyBoundedWhitelistedCleanup(){
        var request=new LoginRequest();request.setUsername("fixture");request.setPassword("fixture");when(auth.login(request)).thenReturn(response());when(limiter.isAllowed("127.0.0.1")).thenReturn(true);
        var incoming=new MockHttpServletRequest();var cookies=new ArrayList<Cookie>();
        for(int index=0;index<40;index++)cookies.add(new Cookie(AuthCookieNames.access(String.format("%043d",index)),"old"));cookies.add(new Cookie("OTHER_APP_COOKIE","keep"));cookies.add(new Cookie("DOOR_HANDLE_TOKEN_bad","keep"));incoming.setCookies(cookies.toArray(Cookie[]::new));
        var result=controller().login(request,incoming,new MockHttpServletResponse());var headers=result.getHeaders().get(HttpHeaders.SET_COOKIE);
        assertThat(headers).hasSize(35);assertThat(headers).filteredOn(h->h.startsWith(AuthCookieNames.SELECTOR+"=")).singleElement().asString().contains("HttpOnly","Path=/","SameSite=Lax").doesNotContain("Domain=");
        assertThat(headers).anyMatch(h->h.startsWith(AuthCookieNames.access(context)+"=access;")).anyMatch(h->h.startsWith(AuthCookieNames.refresh(context)+"=refresh;"));assertThat(headers).noneMatch(h->h.startsWith("OTHER_APP_COOKIE=")||h.startsWith("DOOR_HANDLE_TOKEN_bad="));
    }
    @Test void refreshAndLogoutAddressOnlyTheirSelectedContextWithoutWritingTheSelector(){
        var request=new MockHttpServletRequest();request.addHeader("X-Account-Context",context);request.setCookies(new Cookie(AuthCookieNames.SELECTOR,context),new Cookie(AuthCookieNames.access(context),"selected-access"),new Cookie(AuthCookieNames.refresh(context),"selected-refresh"),new Cookie(AuthController.AUTH_COOKIE_NAME,"legacy-access"),new Cookie(AuthController.REFRESH_COOKIE_NAME,"legacy-refresh"));
        when(auth.refresh("selected-refresh",context)).thenReturn(response());var controller=controller();
        var refresh=controller.refresh(request).getHeaders().get(HttpHeaders.SET_COOKIE);assertThat(refresh).hasSize(2).allMatch(h->!h.startsWith(AuthCookieNames.SELECTOR+"="));
        var logout=controller.logout(request).getHeaders().get(HttpHeaders.SET_COOKIE);assertThat(logout).hasSize(2).allMatch(h->h.contains("Max-Age=0")&&!h.startsWith(AuthCookieNames.SELECTOR+"="));verify(auth).logout("selected-access","selected-refresh",context);verify(auth,never()).refresh("legacy-refresh",context);
    }
    @Test void aValidSelectorNeverFallsBackToAnotherCookieOrBearerHeader()throws Exception{
        var jwt=mock(JwtUtil.class);var users=mock(UserDetailsService.class);var sessions=mock(LoginSessionService.class);when(sessions.enabled()).thenReturn(true);
        var request=new MockHttpServletRequest("GET","/api/auth/check");request.setServletPath("/api/auth/check");request.setCookies(new Cookie(AuthCookieNames.SELECTOR,context),new Cookie(AuthController.AUTH_COOKIE_NAME,"legacy-access"),new Cookie(AuthCookieNames.access("b".repeat(43)),"other-context"));request.addHeader("Authorization","Bearer legacy-access");
        new JwtAuthenticationFilter(jwt,users,new ObjectMapper(),sessions).doFilter(request,new MockHttpServletResponse(),new MockFilterChain());verifyNoInteractions(jwt,users);assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    }
}
