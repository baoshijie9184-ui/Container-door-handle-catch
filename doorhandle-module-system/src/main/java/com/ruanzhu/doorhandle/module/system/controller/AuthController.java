package com.ruanzhu.doorhandle.module.system.controller;

import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.system.dto.LoginRequest;
import com.ruanzhu.doorhandle.module.system.dto.LoginResponse;
import com.ruanzhu.doorhandle.module.system.security.LoginRateLimiter;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import com.ruanzhu.doorhandle.module.system.service.AuthService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Autowired;
import com.ruanzhu.doorhandle.module.system.security.LoginSessionProperties;
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
public class AuthController {
    public static final String AUTH_COOKIE_NAME = "DOOR_HANDLE_TOKEN";
    public static final String REFRESH_COOKIE_NAME = "DOOR_HANDLE_REFRESH_TOKEN";

    private final AuthService authService;
    private final LoginRateLimiter loginRateLimiter;

    private final com.ruanzhu.doorhandle.module.system.service.AccountIdentityService accountIdentities;
    private final LoginSessionProperties sessionProperties;
    @Value("${collaboration.change-history.enabled:false}") private boolean changeHistory;
    @Value("${collaboration.mutations.enabled:false}") private boolean mutations;
    @Value("${collaboration.realtime.enabled:false}") private boolean realtime;
    @Value("${operations.audit.enabled:false}") private boolean baseAudit;
    public AuthController(AuthService auth,LoginRateLimiter limiter,com.ruanzhu.doorhandle.module.system.service.AccountIdentityService identities){this(auth,limiter,identities,new LoginSessionProperties());}
    @Autowired public AuthController(AuthService auth,LoginRateLimiter limiter,com.ruanzhu.doorhandle.module.system.service.AccountIdentityService identities,LoginSessionProperties properties){authService=auth;loginRateLimiter=limiter;accountIdentities=identities;sessionProperties=properties;}

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
                    .header(HttpHeaders.SET_COOKIE, buildAuthCookie(token, cookieLifetime(response.getAccessExpiresAt(),jwtExpirationSeconds)).toString())
                    .header(HttpHeaders.SET_COOKIE, buildRefreshCookie(refreshToken, cookieLifetime(response.getRefreshExpiresAt(),refreshExpirationSeconds)).toString())
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
        LoginResponse response = authService.refresh(token,request.getHeader("X-Account-Context"));
        String access = response.getToken();
        String refresh = response.getRefreshToken();
        response.setToken(null); response.setRefreshToken(null);
        return ResponseEntity.ok()
                .header(HttpHeaders.SET_COOKIE, buildAuthCookie(access, cookieLifetime(response.getAccessExpiresAt(),jwtExpirationSeconds)).toString())
                .header(HttpHeaders.SET_COOKIE, buildRefreshCookie(refresh, cookieLifetime(response.getRefreshExpiresAt(),refreshExpirationSeconds)).toString())
                .body(Result.success(response));
    }

    @PostMapping("/logout")
    public ResponseEntity<Result<Void>> logout(HttpServletRequest request) {
        authService.logout(extractAccessToken(request),extractRefreshToken(request),request.getHeader("X-Account-Context"));
        return clearedCookies();
    }
    private ResponseEntity<Result<Void>> clearedCookies(){
        return ResponseEntity.ok()
                .header(HttpHeaders.SET_COOKIE, buildAuthCookie("", 0L).toString())
                .header(HttpHeaders.SET_COOKIE, buildRefreshCookie("", 0L).toString())
                .body(Result.success(null));
    }
    /** Source compatibility for callers of the original cookie-only controller method. */
    public ResponseEntity<Result<Void>> logout(){authService.logout(null,null,null);return clearedCookies();}

    @GetMapping("/check")
    public Result<Map<String, Object>> checkAuth() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        String username = authentication.getName();

        Map<String, Object> response = new HashMap<>();
        response.put("authenticated", true);
        response.put("capabilities",Map.of("sessionTracking",sessionProperties.isEnabled(),"changeHistory",changeHistory&&baseAudit,"mutations",mutations&&baseAudit,"realtime",realtime&&sessionProperties.isEnabled()&&changeHistory&&baseAudit));
        response.put("username", username);
        response.put("role", authentication.getAuthorities().stream()
                .map(org.springframework.security.core.GrantedAuthority::getAuthority)
                .filter(value -> value.startsWith("ROLE_"))
                .map(value -> value.substring("ROLE_".length()))
                .findFirst().orElse("INSPECTOR"));
        if (authentication.getPrincipal() instanceof TenantPrincipal principal) {
            response.put("userId", principal.userId());
            response.put("identity", accountIdentities.mine(principal));
            response.put("accountContext",principal.accountContext()!=null?principal.accountContext():com.ruanzhu.doorhandle.module.system.service.LoginSessionService.legacyAccountContext(principal.userId(),principal.username()));
        }

        return Result.success(response);
    }

    /**
     * 获取客户端真实 IP
     */
    private String getClientIp(HttpServletRequest request) {
        // A forwarding header is user input unless a separately configured trusted proxy resolves it.
        return request.getRemoteAddr();
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
    private Long cookieLifetime(java.time.Instant expiresAt,Long fallback){return expiresAt==null?fallback:Math.max(0L,java.time.Duration.between(java.time.Instant.now(),expiresAt).getSeconds());}

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
    private String extractAccessToken(HttpServletRequest request){
        String authorization=request.getHeader("Authorization");
        if(authorization!=null&&authorization.startsWith("Bearer "))return authorization.substring(7);
        if(request.getCookies()!=null)for(var cookie:request.getCookies())if(AUTH_COOKIE_NAME.equals(cookie.getName()))return cookie.getValue();
        return null;
    }
}
