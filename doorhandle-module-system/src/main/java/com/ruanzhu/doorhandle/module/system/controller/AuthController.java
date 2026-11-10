package com.ruanzhu.doorhandle.module.system.controller;

import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.system.dto.LoginRequest;
import com.ruanzhu.doorhandle.module.system.dto.LoginResponse;
import com.ruanzhu.doorhandle.module.system.security.LoginRateLimiter;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import com.ruanzhu.doorhandle.module.system.security.AuthCookieNames;
import com.ruanzhu.doorhandle.module.system.service.LoginSessionService;
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
            var result=ResponseEntity.ok();String context=sessionProperties.isEnabled()?response.getAccountContext():null;
            if(sessionProperties.isEnabled()&&!AuthCookieNames.validContext(context))throw new IllegalStateException("登录会话缺少有效上下文");
            if(context!=null){
                if(!AuthCookieNames.validContext(context))throw new IllegalStateException("登录会话缺少有效上下文");
                // Bound response headers and delete only this application's strictly named scoped cookies.
                var obsolete=new java.util.TreeSet<String>();
                if(httpRequest.getCookies()!=null)for(var cookie:httpRequest.getCookies())if(AuthCookieNames.scoped(cookie.getName())
                        &&!cookie.getName().equals(AuthCookieNames.access(context))&&!cookie.getName().equals(AuthCookieNames.refresh(context)))obsolete.add(cookie.getName());
                obsolete.stream().limit(32).forEach(name->result.header(HttpHeaders.SET_COOKIE,
                        cookie(name,"",0L,name.startsWith(REFRESH_COOKIE_NAME+"_")?"/api/auth":"/").toString()));
                result.header(HttpHeaders.SET_COOKIE,cookie(AuthCookieNames.SELECTOR,context,cookieLifetime(response.getRefreshExpiresAt(),refreshExpirationSeconds),"/").toString());
            }
            return result.header(HttpHeaders.SET_COOKIE,buildAuthCookie(context,token,cookieLifetime(response.getAccessExpiresAt(),jwtExpirationSeconds)).toString())
                    .header(HttpHeaders.SET_COOKIE,buildRefreshCookie(context,refreshToken,cookieLifetime(response.getRefreshExpiresAt(),refreshExpirationSeconds)).toString()).body(Result.success(response));
        } catch (Exception e) {
            // 登录失败，记录尝试
            loginRateLimiter.recordFailedAttempt(clientIp);
            throw e;
        }
    }

    @PostMapping("/refresh")
    public ResponseEntity<?> refresh(HttpServletRequest request) {
        String context=selectedForWrite(request);
        String token = extractRefreshToken(request);
        LoginResponse response = authService.refresh(token,request.getHeader("X-Account-Context"));
        String access = response.getToken();
        String refresh = response.getRefreshToken();
        response.setToken(null); response.setRefreshToken(null);
        return ResponseEntity.ok()
                .header(HttpHeaders.SET_COOKIE, buildAuthCookie(context,access, cookieLifetime(response.getAccessExpiresAt(),jwtExpirationSeconds)).toString())
                .header(HttpHeaders.SET_COOKIE, buildRefreshCookie(context,refresh, cookieLifetime(response.getRefreshExpiresAt(),refreshExpirationSeconds)).toString())
                .body(Result.success(response));
    }

    @PostMapping("/logout")
    public ResponseEntity<Result<Void>> logout(HttpServletRequest request) {
        String context=selectedForWrite(request);
        authService.logout(extractAccessToken(request),extractRefreshToken(request),request.getHeader("X-Account-Context"));
        return clearedCookies(context);
    }
    private String selectedForWrite(HttpServletRequest request){
        String context=sessionProperties.isEnabled()?AuthCookieNames.selected(request):null;
        if(context!=null)LoginSessionService.context(context,request.getHeader("X-Account-Context"));return context;
    }
    private ResponseEntity<Result<Void>> clearedCookies(String context){
        return ResponseEntity.ok()
                .header(HttpHeaders.SET_COOKIE, buildAuthCookie(context,"", 0L).toString())
                .header(HttpHeaders.SET_COOKIE, buildRefreshCookie(context,"", 0L).toString())
                .body(Result.success(null));
    }
    /** Source compatibility for callers of the original cookie-only controller method. */
    public ResponseEntity<Result<Void>> logout(){authService.logout(null,null,null);return clearedCookies(null);}

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
            response.put("userId", principal.userId()==null?null:principal.userId().toString());
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
        return buildAuthCookie(null,token,maxAgeSeconds);
    }
    private ResponseCookie buildAuthCookie(String context,String token,Long maxAgeSeconds){return cookie(context==null?AUTH_COOKIE_NAME:AuthCookieNames.access(context),token,maxAgeSeconds,"/");}
    private ResponseCookie cookie(String name,String token,Long maxAgeSeconds,String path){
        return ResponseCookie.from(name, token == null ? "" : token)
                .httpOnly(true)
                .secure(Boolean.TRUE.equals(cookieSecure))
                .path(path)
                .maxAge(maxAgeSeconds == null ? 0L : maxAgeSeconds)
                .sameSite("Lax")
                .build();
    }
    private Long cookieLifetime(java.time.Instant expiresAt, Long fallback) {
        // 保留可空配置值，交由 cookie() 统一按零秒处理。
        if (expiresAt == null) {
            return fallback;
        }
        return Math.max(0L, java.time.Duration.between(java.time.Instant.now(), expiresAt).getSeconds());
    }

    private ResponseCookie buildRefreshCookie(String token, Long maxAgeSeconds) {
        return buildRefreshCookie(null,token,maxAgeSeconds);
    }
    private ResponseCookie buildRefreshCookie(String context,String token,Long maxAgeSeconds){return cookie(context==null?REFRESH_COOKIE_NAME:AuthCookieNames.refresh(context),token,maxAgeSeconds,"/api/auth");}

    private String extractRefreshToken(HttpServletRequest request) {
        if(sessionProperties.isEnabled()){String selected=AuthCookieNames.selected(request);if(selected!=null)return AuthCookieNames.value(request,AuthCookieNames.refresh(selected));}
        if (request.getCookies() != null) for (var c : request.getCookies())
            if (REFRESH_COOKIE_NAME.equals(c.getName())) return c.getValue();
        return request.getHeader("X-Refresh-Token");
    }
    private String extractAccessToken(HttpServletRequest request){
        if(sessionProperties.isEnabled()){String selected=AuthCookieNames.selected(request);if(selected!=null)return AuthCookieNames.value(request,AuthCookieNames.access(selected));}
        String authorization=request.getHeader("Authorization");
        if(authorization!=null&&authorization.startsWith("Bearer "))return authorization.substring(7);
        if(request.getCookies()!=null)for(var cookie:request.getCookies())if(AUTH_COOKIE_NAME.equals(cookie.getName()))return cookie.getValue();
        return null;
    }
}
