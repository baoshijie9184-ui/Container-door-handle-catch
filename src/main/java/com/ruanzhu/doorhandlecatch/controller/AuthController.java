package com.ruanzhu.doorhandlecatch.controller;

import com.ruanzhu.doorhandlecatch.common.Result;
import com.ruanzhu.doorhandlecatch.dto.LoginRequest;
import com.ruanzhu.doorhandlecatch.dto.LoginResponse;
import com.ruanzhu.doorhandlecatch.security.LoginRateLimiter;
import com.ruanzhu.doorhandlecatch.security.TenantPrincipal;
import com.ruanzhu.doorhandlecatch.service.AuthService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/auth")
@RequiredArgsConstructor
public class AuthController {
    public static final String AUTH_COOKIE_NAME = "DOOR_HANDLE_TOKEN";
    public static final String REFRESH_COOKIE_NAME = "DOOR_HANDLE_REFRESH_TOKEN";

    private final AuthService authService;
    private final LoginRateLimiter loginRateLimiter;

    @Value("${jwt.expiration:86400}")
    private Long jwtExpirationSeconds;
    @Value("${jwt.refresh-expiration:2592000}")
    private Long refreshExpirationSeconds;

    @Value("${app.security.cookie-secure:false}")
    private Boolean cookieSecure;

    @PostMapping("/login")
    public ResponseEntity<?> login(@Valid @RequestBody LoginRequest request,
                                   HttpServletRequest httpRequest,
                                   HttpServletResponse httpResponse) {
        String clientIp = getClientIp(httpRequest);

        // 检查速率限制
        if (!loginRateLimiter.isAllowed(clientIp)) {
            long waitSeconds = loginRateLimiter.getRemainingWaitSeconds(clientIp);
            Map<String, Object> errorResponse = new HashMap<>();
            errorResponse.put("code", 429);
            errorResponse.put("message", "登录尝试次数过多，请 " + waitSeconds + " 秒后再试");
            return ResponseEntity.status(HttpStatus.TOO_MANY_REQUESTS).body(errorResponse);
        }

        try {
            LoginResponse response = authService.login(request);
            // 登录成功，清除失败记录
            loginRateLimiter.recordSuccess(clientIp);
            String token = response.getToken();
            String refreshToken = response.getRefreshToken();
            response.setToken(null);
            response.setRefreshToken(null);
            return ResponseEntity.ok()
                    .header(HttpHeaders.SET_COOKIE, buildAuthCookie(token, jwtExpirationSeconds).toString())
                    .header(HttpHeaders.SET_COOKIE, buildRefreshCookie(refreshToken, refreshExpirationSeconds).toString())
                    .body(Result.success(response));
        } catch (Exception e) {
            // 登录失败，记录尝试
            loginRateLimiter.recordFailedAttempt(clientIp);
            throw e;
        }
    }

    @PostMapping("/refresh")
    public ResponseEntity<?> refresh(HttpServletRequest request) {
        String token = extractRefreshToken(request);
        LoginResponse response = authService.refresh(token);
        String access = response.getToken();
        String refresh = response.getRefreshToken();
        response.setToken(null); response.setRefreshToken(null);
        return ResponseEntity.ok()
                .header(HttpHeaders.SET_COOKIE, buildAuthCookie(access, jwtExpirationSeconds).toString())
                .header(HttpHeaders.SET_COOKIE, buildRefreshCookie(refresh, refreshExpirationSeconds).toString())
                .body(Result.success(response));
    }

    @PostMapping("/logout")
    public ResponseEntity<Result<Void>> logout() {
        return ResponseEntity.ok()
                .header(HttpHeaders.SET_COOKIE, buildAuthCookie("", 0L).toString())
                .header(HttpHeaders.SET_COOKIE, buildRefreshCookie("", 0L).toString())
                .body(Result.success(null));
    }

    @GetMapping("/check")
    public Result<Map<String, Object>> checkAuth() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        String username = authentication.getName();

        Map<String, Object> response = new HashMap<>();
        response.put("authenticated", true);
        response.put("username", username);
        if (authentication.getPrincipal() instanceof TenantPrincipal principal) {
            response.put("userId", principal.userId());
        }

        return Result.success(response);
    }

    /**
     * 获取客户端真实 IP
     */
    private String getClientIp(HttpServletRequest request) {
        String ip = request.getHeader("X-Forwarded-For");
        if (ip == null || ip.isEmpty() || "unknown".equalsIgnoreCase(ip)) {
            ip = request.getHeader("Proxy-Client-IP");
        }
        if (ip == null || ip.isEmpty() || "unknown".equalsIgnoreCase(ip)) {
            ip = request.getHeader("WL-Proxy-Client-IP");
        }
        if (ip == null || ip.isEmpty() || "unknown".equalsIgnoreCase(ip)) {
            ip = request.getHeader("HTTP_X_FORWARDED_FOR");
        }
        if (ip == null || ip.isEmpty() || "unknown".equalsIgnoreCase(ip)) {
            ip = request.getHeader("HTTP_X_FORWARDED");
        }
        if (ip == null || ip.isEmpty() || "unknown".equalsIgnoreCase(ip)) {
            ip = request.getHeader("HTTP_FORWARDED_FOR");
        }
        if (ip == null || ip.isEmpty() || "unknown".equalsIgnoreCase(ip)) {
            ip = request.getHeader("HTTP_FORWARDED");
        }
        if (ip == null || ip.isEmpty() || "unknown".equalsIgnoreCase(ip)) {
            ip = request.getHeader("HTTP_CLIENT_IP");
        }
        if (ip == null || ip.isEmpty() || "unknown".equalsIgnoreCase(ip)) {
            ip = request.getRemoteAddr();
        }
        // 多个代理时取第一个
        if (ip != null && ip.contains(",")) {
            ip = ip.split(",")[0].trim();
        }
        return ip;
    }

    private ResponseCookie buildAuthCookie(String token, Long maxAgeSeconds) {
        return ResponseCookie.from(AUTH_COOKIE_NAME, token == null ? "" : token)
                .httpOnly(true)
                .secure(Boolean.TRUE.equals(cookieSecure))
                .path("/")
                .maxAge(maxAgeSeconds == null ? 0L : maxAgeSeconds)
                .sameSite("Lax")
                .build();
    }

    private ResponseCookie buildRefreshCookie(String token, Long maxAgeSeconds) {
        return ResponseCookie.from(REFRESH_COOKIE_NAME, token == null ? "" : token)
                .httpOnly(true).secure(Boolean.TRUE.equals(cookieSecure)).path("/api/auth")
                .maxAge(maxAgeSeconds == null ? 0L : maxAgeSeconds).sameSite("Lax").build();
    }

    private String extractRefreshToken(HttpServletRequest request) {
        if (request.getCookies() != null) for (var c : request.getCookies())
            if (REFRESH_COOKIE_NAME.equals(c.getName())) return c.getValue();
        return request.getHeader("X-Refresh-Token");
    }
}
