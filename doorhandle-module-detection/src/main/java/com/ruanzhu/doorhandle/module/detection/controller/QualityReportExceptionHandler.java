package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.common.*;
import org.springframework.core.annotation.Order;
import org.springframework.dao.*;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.bind.MethodArgumentNotValidException;

@Order(-2)
@RestControllerAdvice(assignableTypes=QualityReportController.class)
public class QualityReportExceptionHandler {
    @ExceptionHandler(BusinessException.class) public ResponseEntity<Result<Void>> business(BusinessException error){return ResponseEntity.status(error.getCode()).body(Result.error(error.getCode(),error.getMessage()));}
    @ExceptionHandler(SecurityException.class) public ResponseEntity<Result<Void>> denied(){return ResponseEntity.status(403).body(Result.error(403,"当前账号没有此报告操作权限"));}
    @ExceptionHandler({DataIntegrityViolationException.class,PessimisticLockingFailureException.class}) public ResponseEntity<Result<Void>> conflict(){return ResponseEntity.status(409).body(Result.error(409,"报告操作发生并发冲突，请刷新后重试"));}
    @ExceptionHandler({MethodArgumentNotValidException.class,org.springframework.http.converter.HttpMessageNotReadableException.class})
    public ResponseEntity<Result<Void>> invalid(){return ResponseEntity.badRequest().body(Result.error(400,"报告请求参数不正确"));}
    @ExceptionHandler(IllegalStateException.class) public ResponseEntity<Result<Void>> failed(){return ResponseEntity.internalServerError().body(Result.error(500,"报告操作失败，请刷新后核对状态"));}
}
