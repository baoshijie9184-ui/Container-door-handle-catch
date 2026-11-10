package com.ruanzhu.doorhandle.module.system.controller;

import com.ruanzhu.doorhandle.module.system.service.AccountContextChangedException;
import org.springframework.core.annotation.Order;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.AuthenticationException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import java.util.Map;

@Order(-10)
@RestControllerAdvice(assignableTypes=AuthController.class)
public class LoginSessionExceptionHandler {
    @ExceptionHandler(AccountContextChangedException.class) public ResponseEntity<?> changed(AccountContextChangedException failure){
        return ResponseEntity.status(409).body(Map.of("code","ACCOUNT_CONTEXT_CHANGED","message",failure.getMessage()));
    }
    @ExceptionHandler(AuthenticationException.class) public ResponseEntity<?> invalid(AuthenticationException failure){
        return ResponseEntity.status(401).body(Map.of("code",401,"message","登录会话无效或账号不具备登录资格"));
    }
}
