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
import lombok.RequiredArgsConstructor;
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
@RequiredArgsConstructor
public class JwtAuthenticationFilter extends OncePerRequestFilter {
    private final JwtUtil jwtUtil;
    private final UserDetailsService userDetailsService;
    private final ObjectMapper objectMapper;

    // 白名单接口不做 JWT 校验（与 SecurityConfig 中 permitAll 的路径保持一致）。
    private final List<String> whiteList = Arrays.asList(
            "/api/auth/login",
            "/api/auth/logout",
            "/swagger-ui/",
            "/v3/api-docs/",
            "/error"
    );

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        String requestPath = request.getServletPath();
        if (isWhitelisted(requestPath)) {
            log.debug("白名单路径，跳过 JWT 校验: {}", requestPath);
            filterChain.doFilter(request, response);
            return;
        }

        final String jwt = resolveToken(request);
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

            if (SecurityContextHolder.getContext().getAuthentication() == null) {
                UserDetails userDetails = this.userDetailsService.loadUserByUsername(username);
                log.debug("加载用户详情成功: {}", username);

                boolean tenantMatches = userDetails instanceof TenantPrincipal principal
                        && userId.equals(principal.userId());
                // 兼容历史 JWT（无 type claim），但明确拒绝 refresh token 访问业务接口。
                if (jwtUtil.validateToken(jwt) && !jwtUtil.isRefreshToken(jwt) && tenantMatches) {
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
            filterChain.doFilter(request, response);
        } catch (Exception e) {
            log.error("JWT 认证异常: {}", e.getMessage());
            handleAuthenticationException(response, e);
        }
    }

    /**
     * 判断当前请求路径是否命中白名单。
     */
    private boolean isWhitelisted(String requestPath) {
        return whiteList.stream().anyMatch(requestPath::startsWith);
    }

    private String resolveToken(HttpServletRequest request) {
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

        Result<?> result = Result.error(HttpStatus.UNAUTHORIZED.value(), "认证失败: " + e.getMessage());
        response.getWriter().write(objectMapper.writeValueAsString(result));
    }
}
