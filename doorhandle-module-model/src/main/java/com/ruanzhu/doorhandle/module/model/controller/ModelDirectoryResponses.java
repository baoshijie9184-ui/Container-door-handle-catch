package com.ruanzhu.doorhandle.module.model.controller;

import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import org.springframework.beans.BeanUtils;
import org.springframework.security.core.context.SecurityContextHolder;

final class ModelDirectoryResponses {
    private ModelDirectoryResponses() {}

    static boolean includesStoragePath() {
        var authentication = SecurityContextHolder.getContext().getAuthentication();
        return authentication != null && authentication.isAuthenticated() && authentication.getAuthorities().stream()
                .anyMatch(authority -> "ROLE_SUPERVISOR".equals(authority.getAuthority()));
    }

    static ModelInfo withoutStoragePath(ModelInfo model) {
        if (model.getModelPath() == null) return model;
        var response = new ModelInfo();
        BeanUtils.copyProperties(model, response, "modelPath");
        return response;
    }
}
