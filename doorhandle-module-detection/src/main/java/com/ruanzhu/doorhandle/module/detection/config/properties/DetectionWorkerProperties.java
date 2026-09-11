package com.ruanzhu.doorhandle.module.detection.config.properties;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Data
@Configuration
@ConfigurationProperties(prefix = "app.detection-worker")
public class DetectionWorkerProperties {
    private boolean enabled = false;
    private String deployment = "remote";
    private String label = "remote-python-worker";
}
