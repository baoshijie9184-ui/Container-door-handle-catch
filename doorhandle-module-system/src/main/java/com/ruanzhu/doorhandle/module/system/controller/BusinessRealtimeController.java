package com.ruanzhu.doorhandle.module.system.controller;

import com.ruanzhu.doorhandle.module.system.realtime.BusinessRealtimeService;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import java.net.URI;
import java.time.Instant;

@RestController
@RequestMapping("/api/realtime")
@ConditionalOnProperty(prefix = "collaboration.realtime", name = "enabled", havingValue = "true")
public class BusinessRealtimeController {
    private final BusinessRealtimeService realtime;
    private final Environment environment;
    public BusinessRealtimeController(BusinessRealtimeService realtime, Environment environment) { this.realtime = realtime; this.environment = environment; }

    @GetMapping(value = "/changes", produces = "text/event-stream;charset=UTF-8")
    public ResponseEntity<SseEmitter> changes(@AuthenticationPrincipal TenantPrincipal principal, HttpServletRequest request) {
        if (!environment.getProperty("collaboration.sessions.enabled", Boolean.class, false)
                || !environment.getProperty("operations.audit.enabled", Boolean.class, false)
                || !environment.getProperty("collaboration.change-history.enabled", Boolean.class, false))
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "协同会话及修改历史尚未启用");
        if (principal == null || !principal.isEnabled() || principal.sessionDigest() == null || principal.sessionDigest().isBlank())
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED);
        sameOrigin(request);
        Object expires = request.getAttribute("doorhandle.auth.accessExpiresAt");
        if (!(expires instanceof Instant expiry)) throw new ResponseStatusException(HttpStatus.UNAUTHORIZED);
        return ResponseEntity.ok().header("Cache-Control", "no-cache, no-store, no-transform")
                .header("X-Accel-Buffering", "no")
                .body(realtime.open(principal.userId(), principal.username(), principal.sessionDigest(), principal.accountContext(), expiry));
    }
    static void sameOrigin(HttpServletRequest request) {
        if ("cross-site".equalsIgnoreCase(request.getHeader("Sec-Fetch-Site"))) throw new ResponseStatusException(HttpStatus.FORBIDDEN);
        String source = request.getHeader("Origin");
        if (source == null) source = request.getHeader("Referer");
        if (source == null) return; // Same-origin EventSource GET may omit both; the authenticated cookie is still required.
        try {
            URI uri = URI.create(source);
            int port = uri.getPort() >= 0 ? uri.getPort() : "https".equalsIgnoreCase(uri.getScheme()) ? 443 : 80;
            if (uri.getUserInfo() != null || uri.getHost() == null || !request.getScheme().equalsIgnoreCase(uri.getScheme())
                    || !request.getServerName().equalsIgnoreCase(uri.getHost()) || request.getServerPort() != port)
                throw new IllegalArgumentException();
        } catch (IllegalArgumentException invalid) { throw new ResponseStatusException(HttpStatus.FORBIDDEN); }
    }
}
