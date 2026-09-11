package com.ruanzhu.doorhandle.module.model.service;

import java.nio.file.Path;

/**
 * 模型文件校验服务。
 */
public interface ModelValidationService {

    ValidationResult validate(Path modelPath);

    record ValidationResult(String status, String message) {
    }
}
