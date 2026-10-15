package com.ruanzhu.doorhandle.module.system.security;

import com.ruanzhu.doorhandle.common.Result;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/** 方法权限拒绝必须是 HTTP 403，不能落入通用的 HTTP 200 系统异常包装。 */
@RestControllerAdvice
@Order(Ordered.HIGHEST_PRECEDENCE)
public class AuthorizationExceptionHandler {
    @ExceptionHandler(AccessDeniedException.class)
    public ResponseEntity<Result<Void>> denied() {
        return ResponseEntity.status(403).body(Result.error(403,"当前账号没有此操作权限"));
    }
}
