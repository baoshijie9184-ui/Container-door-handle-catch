package com.ruanzhu.doorhandle.module.app.config;

import com.ruanzhu.doorhandle.module.detection.config.properties.DetectionWorkerProperties;
import com.ruanzhu.doorhandle.module.detection.config.properties.KafkaTaskProperties;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;

@Component("industrialPlatform")
@RequiredArgsConstructor
public class IndustrialPlatformHealthIndicator implements HealthIndicator {

    private final KafkaTaskProperties kafkaTaskProperties;
    private final DetectionWorkerProperties detectionWorkerProperties;

    @Value("${model.upload-dir:${user.dir}/uploads/models}")
    private String modelUploadDir;

    @Value("${detection.upload-dir:${user.dir}/uploads/images}")
    private String detectionUploadDir;

    @Value("${detection.result-dir:${user.dir}/uploads/results}")
    private String detectionResultDir;

    @Override
    public Health health() {
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("kafka", kafkaDetails());
        details.put("detectionWorker", workerDetails());
        details.put("storage", storageDetails());
        return Health.up().withDetails(details).build();
    }

    private Map<String, Object> kafkaDetails() {
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("enabled", kafkaTaskProperties.isEnabled());
        details.put("bootstrapConfigured", StringUtils.hasText(kafkaTaskProperties.getBootstrapServers()));
        details.put("consumerGroup", kafkaTaskProperties.getConsumerGroup());
        return details;
    }

    private Map<String, Object> workerDetails() {
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("enabled", detectionWorkerProperties.isEnabled());
        details.put("deployment", detectionWorkerProperties.getDeployment());
        details.put("label", detectionWorkerProperties.getLabel());
        return details;
    }

    private Map<String, Object> storageDetails() {
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("modelUploadDir", pathDetails(modelUploadDir));
        details.put("detectionUploadDir", pathDetails(detectionUploadDir));
        details.put("detectionResultDir", pathDetails(detectionResultDir));
        return details;
    }

    private Map<String, Object> pathDetails(String rawPath) {
        Path path = Path.of(rawPath).toAbsolutePath().normalize();
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("path", path.toString());
        details.put("exists", Files.exists(path));
        details.put("readable", Files.isReadable(path));
        details.put("writable", Files.isWritable(path));
        return details;
    }
}
