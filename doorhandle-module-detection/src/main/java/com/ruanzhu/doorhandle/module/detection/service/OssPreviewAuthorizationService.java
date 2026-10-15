package com.ruanzhu.doorhandle.module.detection.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.Authentication;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.Collections;
import java.util.List;

@Service
@RequiredArgsConstructor
public class OssPreviewAuthorizationService {

    private static final String ALLOWED_PREFIX = "detection/";

    private final DetectionTaskMapper detectionTaskMapper;
    private final ObjectMapper objectMapper;
    private final DetectionTaskAccessPolicy accessPolicy;

    public void authorize(String key, Authentication authentication) {
        if (!StringUtils.hasText(key) || !key.startsWith(ALLOWED_PREFIX)) {
            throw denied();
        }
        accessPolicy.assertAuthenticated(authentication);
        LambdaQueryWrapper<DetectionTask> query = new LambdaQueryWrapper<>();
        accessPolicy.applyScope(query, authentication);
        query.and(candidate -> candidate
                .eq(DetectionTask::getResultJsonOssKey, key)
                .or()
                .like(DetectionTask::getOriginalImageKeysJson, key)
                .or()
                .like(DetectionTask::getPreviewImageKeysJson, key));

        DetectionTask referencedTask = detectionTaskMapper.selectList(query).stream()
                .filter(task -> accessPolicy.canAccess(task, authentication.getName(), accessPolicy.isAdmin(authentication)))
                .filter(task -> references(task, key))
                .findFirst()
                .orElseThrow(this::denied);
        accessPolicy.assertCanAccess(referencedTask, authentication);
    }

    private boolean references(DetectionTask task, String key) {
        return key.equals(task.getResultJsonOssKey())
                || readKeys(task.getOriginalImageKeysJson()).contains(key)
                || readKeys(task.getPreviewImageKeysJson()).contains(key);
    }

    private List<String> readKeys(String json) {
        if (!StringUtils.hasText(json)) {
            return Collections.emptyList();
        }
        try {
            return objectMapper.readValue(json, new TypeReference<>() { });
        } catch (Exception ignored) {
            return Collections.emptyList();
        }
    }

    private BusinessException denied() {
        return new BusinessException(403, "无权访问该资源");
    }
}
