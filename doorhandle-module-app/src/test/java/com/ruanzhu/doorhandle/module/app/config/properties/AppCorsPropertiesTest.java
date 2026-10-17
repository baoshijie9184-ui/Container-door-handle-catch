package com.ruanzhu.doorhandle.module.app.config.properties;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AppCorsPropertiesTest {

    @Test
    void defaultOriginsSupportLocalhostAndLoopbackFrontend() {
        AppCorsProperties properties = new AppCorsProperties();

        assertThat(properties.getAllowedOrigins())
                .contains("http://localhost:3001", "http://127.0.0.1:3001");
    }

    @Test
    void allowedFrontendCanReadPdfPageHeadersAndForeignOriginsRemainRejected() throws Exception {
        var properties = new AppCorsProperties();
        var security = new com.ruanzhu.doorhandle.module.app.config.SecurityConfig(
                org.mockito.Mockito.mock(com.ruanzhu.doorhandle.module.system.security.JwtAuthenticationFilter.class), properties);
        var filter = new org.springframework.web.filter.CorsFilter(security.corsConfigurationSource());
        var request = new org.springframework.mock.web.MockHttpServletRequest("GET", "/api/agent/conversations/mine/files/pdf/preview");
        request.addHeader("Origin", "http://localhost:3001");
        var response = new org.springframework.mock.web.MockHttpServletResponse();
        filter.doFilter(request, response, (req, res) -> ((jakarta.servlet.http.HttpServletResponse)res).setHeader("X-PDF-Pages", "2"));
        assertThat(response.getHeader("Access-Control-Allow-Origin")).isEqualTo("http://localhost:3001");
        assertThat(response.getHeader("Access-Control-Expose-Headers")).contains("X-PDF-Page", "X-PDF-Pages");
        assertThat(response.getHeader("X-PDF-Pages")).isEqualTo("2");
        var foreign = new org.springframework.mock.web.MockHttpServletRequest("GET", request.getRequestURI());
        foreign.addHeader("Origin", "https://foreign.invalid");
        var denied = new org.springframework.mock.web.MockHttpServletResponse();
        filter.doFilter(foreign, denied, (req, res) -> { throw new AssertionError("Foreign origin reached file delivery"); });
        assertThat(denied.getStatus()).isEqualTo(403);
    }
}
