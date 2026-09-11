package com.ruanzhu.doorhandle.module.system.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.system.util.JwtUtil;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.core.userdetails.UserDetailsService;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class JwtAuthenticationFilterTest {

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void authenticatesFileRequestsFromHttpOnlyCookieWhenAuthorizationHeaderIsAbsent() throws Exception {
        JwtUtil jwtUtil = mock(JwtUtil.class);
        UserDetailsService userDetailsService = mock(UserDetailsService.class);
        JwtAuthenticationFilter filter = new JwtAuthenticationFilter(jwtUtil, userDetailsService, new ObjectMapper());
        when(jwtUtil.getUsernameFromToken("cookie-token")).thenReturn("alice");
        when(jwtUtil.getUserIdFromToken("cookie-token")).thenReturn(42L);
        when(jwtUtil.validateToken("cookie-token")).thenReturn(true);
        when(userDetailsService.loadUserByUsername("alice")).thenReturn(
                new TenantPrincipal(42L, "alice", "N/A", List.of())
        );

        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/files/images/batch/img.jpg");
        request.setServletPath("/api/files/images/batch/img.jpg");
        request.setCookies(new Cookie("DOOR_HANDLE_TOKEN", "cookie-token"));
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, new MockFilterChain());

        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNotNull();
        assertThat(SecurityContextHolder.getContext().getAuthentication().getName()).isEqualTo("alice");
        assertThat(SecurityContextHolder.getContext().getAuthentication().getPrincipal())
                .isInstanceOf(TenantPrincipal.class)
                .extracting("userId").isEqualTo(42L);
    }

    @Test
    void authenticatesAuthCheckRequestsInsteadOfWhitelistingThem() throws Exception {
        JwtUtil jwtUtil = mock(JwtUtil.class);
        UserDetailsService userDetailsService = mock(UserDetailsService.class);
        JwtAuthenticationFilter filter = new JwtAuthenticationFilter(jwtUtil, userDetailsService, new ObjectMapper());
        when(jwtUtil.getUsernameFromToken("header-token")).thenReturn("alice");
        when(jwtUtil.getUserIdFromToken("header-token")).thenReturn(42L);
        when(jwtUtil.validateToken("header-token")).thenReturn(true);
        when(userDetailsService.loadUserByUsername("alice")).thenReturn(
                new TenantPrincipal(42L, "alice", "N/A", List.of())
        );

        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/auth/check");
        request.setServletPath("/api/auth/check");
        request.addHeader("Authorization", "Bearer header-token");
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, new MockFilterChain());

        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNotNull();
        assertThat(SecurityContextHolder.getContext().getAuthentication().getName()).isEqualTo("alice");
    }

    @Test
    void rejectsTokenWhenImmutableUserIdDoesNotMatchLoadedUser() throws Exception {
        JwtUtil jwtUtil = mock(JwtUtil.class);
        UserDetailsService userDetailsService = mock(UserDetailsService.class);
        JwtAuthenticationFilter filter = new JwtAuthenticationFilter(jwtUtil, userDetailsService, new ObjectMapper());
        when(jwtUtil.getUsernameFromToken("token")).thenReturn("alice");
        when(jwtUtil.getUserIdFromToken("token")).thenReturn(99L);
        when(jwtUtil.validateToken("token")).thenReturn(true);
        when(userDetailsService.loadUserByUsername("alice"))
                .thenReturn(new TenantPrincipal(42L, "alice", "N/A", List.of()));
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/auth/check");
        request.setServletPath("/api/auth/check");
        request.addHeader("Authorization", "Bearer token");
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, new MockFilterChain());

        assertThat(response.getStatus()).isEqualTo(401);
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    }
}
