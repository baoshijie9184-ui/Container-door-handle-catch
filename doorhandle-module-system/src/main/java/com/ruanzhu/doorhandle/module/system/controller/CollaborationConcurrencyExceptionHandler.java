package com.ruanzhu.doorhandle.module.system.controller;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.dao.ConcurrencyFailureException;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import java.util.Map;

/** A failed concurrency transaction has already unwound before this HTTP boundary. */
@RestControllerAdvice
@Order(Ordered.HIGHEST_PRECEDENCE)
@ConditionalOnProperty(prefix="collaboration.mutations",name="enabled",havingValue="true")
public class CollaborationConcurrencyExceptionHandler {
    @ExceptionHandler(ConcurrencyFailureException.class)
    public ResponseEntity<Map<String,String>> concurrentWrite() {
        return ResponseEntity.status(409).header("Cache-Control","no-store").body(Map.of(
                "code","CONCURRENT_WRITE",
                "message","并发修改未完成，请保留草稿并核对最新资料后重试"));
    }
}
