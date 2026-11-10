package com.ruanzhu.doorhandle.module.system.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.system.controller.AuthController;
import com.ruanzhu.doorhandle.module.system.util.JwtUtil;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Autowired;
import com.ruanzhu.doorhandle.module.system.service.LoginSessionService;
import com.ruanzhu.doorhandle.module.system.service.AccountContextChangedException;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.web.authentication.WebAuthenticationDetailsSource;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.Arrays;
import java.util.List;

@Slf4j
@Component
public class JwtAuthenticationFilter extends OncePerRequestFilter {
    private final JwtUtil jwtUtil;
    private final UserDetailsService userDetailsService;
    private final ObjectMapper objectMapper;
    private final LoginSessionService sessions;
    public JwtAuthenticationFilter(JwtUtil jwt,UserDetailsService users,ObjectMapper json){this(jwt,users,json,null);}
    @Autowired public JwtAuthenticationFilter(JwtUtil jwt,UserDetailsService users,ObjectMapper json,LoginSessionService sessions){this.jwtUtil=jwt;this.userDetailsService=users;this.objectMapper=json;this.sessions=sessions;}

    // 白名单接口不做 JWT 校验（与 SecurityConfig 中 permitAll 的路径保持一致）。
    private final List<String> whiteList = Arrays.asList(
            "/api/auth/login",
            "/api/auth/logout",
            "/api/auth/refresh",
            "/swagger-ui/",
            "/v3/api-docs/",
            "/error"
    );

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        String requestPath = request.getServletPath();
        if(sessions!=null&&!List.of("GET","HEAD","OPTIONS").contains(request.getMethod())&&!trustedOrigin(request)){
            response.setStatus(403);response.setContentType(MediaType.APPLICATION_JSON_VALUE);
            response.getWriter().write(objectMapper.writeValueAsString(Result.error(403,"请求来源不受信任")));return;
        }
        if (isWhitelisted(requestPath)) {
            log.debug("白名单路径，跳过 JWT 校验: {}", requestPath);
            filterChain.doFilter(request, response);
            return;
        }

        final String jwt;
        try{jwt=resolveToken(request);}catch(org.springframework.security.core.AuthenticationException invalid){handleTokenInvalid(response);return;}
        if (jwt == null) {
            filterChain.doFilter(request, response);
            return;
        }

        try {
            String username = jwtUtil.getUsernameFromToken(jwt);
            Long userId = jwtUtil.getUserIdFromToken(jwt);

            if (username == null || userId == null) {
                log.warn("JWT 令牌无效，无法解析用户名");
                handleTokenInvalid(response);
                return;
            }

            log.debug("从 JWT 中解析到用户名: {}", username);

            if (SecurityContextHolder.getContext().getAuthentication() == null || (sessions!=null&&sessions.enabled())) {
                com.ruanzhu.doorhandle.contracts.security.LoginSessionAccess.Session active=null;
                if(sessions!=null&&sessions.enabled()){
                    String sid=jwtUtil.getSessionId(jwt);
                    if(!jwtUtil.validateToken(jwt)||!jwtUtil.isAccessToken(jwt)||sid==null){handleTokenInvalid(response);return;}
                    // Current account rejection must reach the durable session service before UserDetails can reject it.
                    active=sessions.requireActive(userId,username,LoginSessionService.digest(sid));
                    String selected=AuthCookieNames.selected(request);
                    if(selected!=null&&!selected.equals(active.accountContext())){handleTokenInvalid(response);return;}
                }
                UserDetails userDetails = this.userDetailsService.loadUserByUsername(username);
                log.debug("加载用户详情成功: {}", username);

                boolean tenantMatches = userDetails instanceof TenantPrincipal principal
                        && userId.equals(principal.userId());
                // 兼容历史 JWT（无 type claim），但明确拒绝 refresh token 访问业务接口。
                if (jwtUtil.validateToken(jwt) && !jwtUtil.isRefreshToken(jwt) && tenantMatches && userDetails.isEnabled()) {
                    if(sessions!=null&&sessions.enabled()){
                        java.time.Instant accessExpiresAt=jwtUtil.getExpiresAt(jwt);
                        if(accessExpiresAt==null||!accessExpiresAt.isAfter(java.time.Instant.now())){handleTokenInvalid(response);return;}
                        request.setAttribute("doorhandle.auth.accessExpiresAt",accessExpiresAt);
                        userDetails=new TenantPrincipal(userId,username,userDetails.getPassword(),List.of(new SimpleGrantedAuthority("ROLE_"+active.role())),active.sessionDigest(),active.accountContext());
                        if(!List.of("GET","HEAD","OPTIONS").contains(request.getMethod()))
                            LoginSessionService.context(active.accountContext(),request.getHeader("X-Account-Context"));
                    }else if(userDetails instanceof TenantPrincipal legacy){
                        String context=LoginSessionService.legacyAccountContext(legacy.userId(),legacy.username());
                        userDetails=new TenantPrincipal(legacy.userId(),legacy.username(),legacy.password(),legacy.authorities(),null,context,legacy.enabled());
                        if(!List.of("GET","HEAD","OPTIONS").contains(request.getMethod())&&request.getHeader("X-Account-Context")!=null)
                            LoginSessionService.context(context,request.getHeader("X-Account-Context"));
                    }
                    log.debug("令牌有效，建立认证上下文");
                    UsernamePasswordAuthenticationToken authToken = new UsernamePasswordAuthenticationToken(
                            userDetails,
                            null,
                            userDetails.getAuthorities()
                    );
                    authToken.setDetails(new WebAuthenticationDetailsSource().buildDetails(request));
                    SecurityContextHolder.getContext().setAuthentication(authToken);
                    log.debug("认证上下文已写入: {}", username);
                } else {
                    log.warn("令牌已过期、无效或租户不匹配: {}", username);
                    handleTokenInvalid(response);
                    return;
                }
            }
        } catch (AccountContextChangedException changed) {
            SecurityContextHolder.clearContext();response.setStatus(409);response.setContentType(MediaType.APPLICATION_JSON_VALUE);
            response.getWriter().write(objectMapper.writeValueAsString(java.util.Map.of("code","ACCOUNT_CONTEXT_CHANGED","message",changed.getMessage())));return;
        } catch (Exception e) {
            SecurityContextHolder.clearContext();
            log.error("JWT 认证异常: {}", e.getMessage());
            handleAuthenticationException(response, e);
            return;
        }
        filterChain.doFilter(request,response);
    }

    /**
     * 判断当前请求路径是否命中白名单。
     */
    private boolean isWhitelisted(String requestPath) {
        return whiteList.stream().anyMatch(path->path.endsWith("/")?requestPath.startsWith(path):requestPath.equals(path));
    }
    /** Browser cookie writes require an exact same-origin source; proxy Host must retain the public host. */
    private boolean trustedOrigin(HttpServletRequest request){
        String supplied=request.getHeader("Origin");
        if(supplied==null){
            String referer=request.getHeader("Referer");
            if(referer==null){
                boolean cookieCredentials=request.getCookies()!=null&&Arrays.stream(request.getCookies()).anyMatch(c->AuthCookieNames.authentication(c.getName()));
                return !cookieCredentials&&((request.getHeader("Authorization")!=null&&request.getHeader("Authorization").startsWith("Bearer "))||request.getHeader("X-Refresh-Token")!=null);
            }
            try {var uri=java.net.URI.create(referer);supplied=uri.getScheme()+"://"+uri.getRawAuthority();}catch(Exception invalid){return false;}
        }
        int port=request.getServerPort();String expected=request.getScheme()+"://"+request.getServerName()+(("https".equals(request.getScheme())&&port==443)||("http".equals(request.getScheme())&&port==80)?"":":"+port);
        return expected.equals(supplied);
    }

    private String resolveToken(HttpServletRequest request) {
        if(sessions!=null&&sessions.enabled()){
            String selected=AuthCookieNames.selected(request);
            if(selected!=null)return AuthCookieNames.value(request,AuthCookieNames.access(selected));
        }
        String authHeader = request.getHeader("Authorization");
        if (authHeader != null && authHeader.startsWith("Bearer ")) {
            return authHeader.substring(7);
        }
        Cookie[] cookies = request.getCookies();
        if (cookies == null) {
            return null;
        }
        return Arrays.stream(cookies)
                .filter(cookie -> AuthController.AUTH_COOKIE_NAME.equals(cookie.getName()))
                .map(Cookie::getValue)
                .filter(value -> value != null && !value.isBlank())
                .findFirst()
                .orElse(null);
    }

    private void handleTokenExpired(HttpServletResponse response) throws IOException {
        response.setStatus(HttpStatus.UNAUTHORIZED.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);

        Result<?> result = Result.error(HttpStatus.UNAUTHORIZED.value(), "令牌已过期，请重新登录");
        response.getWriter().write(objectMapper.writeValueAsString(result));
    }

    private void handleTokenInvalid(HttpServletResponse response) throws IOException {
        response.setStatus(HttpStatus.UNAUTHORIZED.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);

        Result<?> result = Result.error(HttpStatus.UNAUTHORIZED.value(), "令牌无效，请重新登录");
        response.getWriter().write(objectMapper.writeValueAsString(result));
    }

    private void handleAuthenticationException(HttpServletResponse response, Exception e) throws IOException {
        response.setStatus(HttpStatus.UNAUTHORIZED.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);

        Result<?> result = Result.error(HttpStatus.UNAUTHORIZED.value(), "登录会话无效，请重新登录");
        response.getWriter().write(objectMapper.writeValueAsString(result));
    }
}
