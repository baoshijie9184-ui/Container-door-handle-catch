package com.ruanzhu.doorhandle.framework.config.properties;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;

@Data
@Configuration
@ConfigurationProperties(prefix = "app.redis")
public class AppRedisProperties {

    /**
     * Redis 默认关闭，避免开发和测试环境因为没有 Redis 服务而启动失败。
     */
    private boolean enabled = false;

    /**
     * 所有业务 key 的统一前缀，便于隔离环境和后续清理。
     */
    private String keyPrefix = "doorhandlecatch";

    private Duration defaultTtl = Duration.ofMinutes(30);

    private Map<String, Duration> cacheTtls = new LinkedHashMap<>(Map.of(
            "dashboard", Duration.ofMinutes(5),
            "model", Duration.ofMinutes(10),
            "device", Duration.ofMinutes(5),
            "employee", Duration.ofMinutes(10),
            "detection-task", Duration.ofMinutes(2),
            "chat-session", Duration.ofMinutes(15)
    ));
}
