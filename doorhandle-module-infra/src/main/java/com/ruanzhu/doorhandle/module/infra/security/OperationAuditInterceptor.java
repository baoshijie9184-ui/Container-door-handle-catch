package com.ruanzhu.doorhandle.module.infra.security;

import com.ruanzhu.doorhandle.module.infra.service.OperationAuditService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import java.util.Set;

@Slf4j
@Component
@RequiredArgsConstructor
public class OperationAuditInterceptor implements HandlerInterceptor {
    private static final Set<String> MUTATING_METHODS = Set.of("POST", "PUT", "PATCH", "DELETE");
    private final OperationAuditService auditService;

    @Override
    public void afterCompletion(HttpServletRequest request, HttpServletResponse response,
                                Object handler, Exception exception) {
        if (!request.getRequestURI().startsWith("/api/")
                || !MUTATING_METHODS.contains(request.getMethod())) {
            return;
        }
        try {
            auditService.recordHttp(request.getMethod(),request.getRequestURI(),response.getStatus(),request.getRemoteAddr(),exception);
        } catch (Exception auditFailure) {
            log.error("写操作审计失败: {} {}", request.getMethod(), request.getRequestURI(), auditFailure);
        }
    }
}
