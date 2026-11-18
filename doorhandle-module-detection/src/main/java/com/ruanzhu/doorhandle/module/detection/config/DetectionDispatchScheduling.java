package com.ruanzhu.doorhandle.module.detection.config;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;

@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = "detection.commands", name = "enabled", havingValue = "true")
@EnableScheduling
public class DetectionDispatchScheduling {
}
