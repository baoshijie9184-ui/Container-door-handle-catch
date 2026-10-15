package com.ruanzhu.doorhandle.module.system.controller;

import com.ruanzhu.doorhandle.common.*;
import org.springframework.core.annotation.Order;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/** 组织接口保留真实冲突状态，数据库约束信息不直接返回前端。 */
@Order(-1)
@RestControllerAdvice(assignableTypes = OrganizationController.class)
public class OrganizationExceptionHandler {
    @ExceptionHandler(BusinessException.class)
    public ResponseEntity<Result<Void>> business(BusinessException error) {
        return ResponseEntity.status(error.getCode()).body(Result.error(error.getCode(), error.getMessage()));
    }
    @ExceptionHandler(DataIntegrityViolationException.class)
    public ResponseEntity<Result<Void>> constraint() {
        return ResponseEntity.status(409).body(Result.error(409, "账号、员工或部门关联发生冲突，请刷新后重试"));
    }
}
