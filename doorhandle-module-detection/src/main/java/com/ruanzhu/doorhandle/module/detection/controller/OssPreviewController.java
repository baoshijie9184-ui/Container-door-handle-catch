package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.module.infra.config.properties.OssProperties;
import com.ruanzhu.doorhandle.module.infra.service.OssStorageService;
import com.ruanzhu.doorhandle.module.detection.service.OssPreviewAuthorizationService;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.util.StringUtils;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.io.IOException;
import java.time.Duration;

/**
 * OSS 图片预览代理 — 每次请求生成新的预签名 URL 并 302 重定向。
 * 解决预签名 URL 过期导致检测记录图片无法加载的问题。
 */
@RestController
@RequestMapping("/api/oss")
@RequiredArgsConstructor
@Slf4j
public class OssPreviewController {

    private final OssStorageService ossStorageService;
    private final OssProperties ossProperties;
    private final OssPreviewAuthorizationService authorizationService;

    @GetMapping("/preview")
    public void preview(@RequestParam String key, Authentication authentication,
                        HttpServletResponse response) throws IOException {
        if (!StringUtils.hasText(key)) {
            response.sendError(HttpServletResponse.SC_BAD_REQUEST, "缺少 key 参数");
            return;
        }

        authorizationService.authorize(key, authentication);

        if (!ossStorageService.isConfigured()) {
            response.sendError(HttpServletResponse.SC_SERVICE_UNAVAILABLE, "OSS 未配置");
            return;
        }

        try {
            var url = ossStorageService.generateGetUrl(
                    key,
                    Duration.ofMinutes(ossProperties.getPreviewUrlExpireMinutes())
            );
            response.sendRedirect(url.toString());
        } catch (Exception e) {
            log.error("OSS 预览重定向失败: key={}", key, e);
            response.sendError(HttpServletResponse.SC_INTERNAL_SERVER_ERROR, "OSS 预览失败");
        }
    }

}
