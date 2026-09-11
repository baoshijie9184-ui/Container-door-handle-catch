package com.ruanzhu.doorhandle.common;

import org.springframework.util.DigestUtils;

import java.nio.charset.StandardCharsets;

public final class RedisKeys {

    public static final String ROOT = "doorhandlecatch";

    private RedisKeys() {
    }

    public static String detectionTask(String taskId) {
        return join("detection", "task", taskId);
    }

    public static String detectionTaskProgress(String taskId) {
        return join("detection", "task", taskId, "progress");
    }

    public static String deviceStatus(String deviceCode) {
        return join("device", deviceCode, "status");
    }

    public static String modelMetadata(Integer modelId) {
        return join("model", String.valueOf(modelId), "metadata");
    }

    public static String chatSession(String sessionId) {
        return join("chat", "session", sessionId);
    }

    public static String rateLimit(String scope, String identity) {
        return join("rate-limit", scope, digest(identity));
    }

    public static String lock(String resource, String id) {
        return join("lock", resource, id);
    }

    public static String stream(String name) {
        return join("stream", name);
    }

    private static String join(String... parts) {
        return ROOT + ":" + String.join(":", parts);
    }

    private static String digest(String value) {
        return DigestUtils.md5DigestAsHex(value.getBytes(StandardCharsets.UTF_8));
    }
}
