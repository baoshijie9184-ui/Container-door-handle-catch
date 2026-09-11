package com.ruanzhu.doorhandle.module.detection.config.properties;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Data
@Configuration
@ConfigurationProperties(prefix = "app.kafka")
public class KafkaTaskProperties {
    private boolean enabled = false;
    private String bootstrapServers = "localhost:9092";
    private long sendTimeoutMs = 10000L;
    private String consumerGroup = "doorhandlecatch-detection";
    private Topics topics = new Topics();

    @Data
    public static class Topics {
        private String taskCreated = "detection.task.created";
        private String taskFinished = "detection.task.finished";
        private String taskProgress = "detection.task.progress";
    }
}
