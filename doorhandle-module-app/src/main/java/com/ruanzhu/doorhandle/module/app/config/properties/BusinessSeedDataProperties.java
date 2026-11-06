package com.ruanzhu.doorhandle.module.app.config.properties;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

import java.util.ArrayList;
import java.util.List;

@Data
@Configuration
@ConfigurationProperties(prefix = "app.business-seed")
public class BusinessSeedDataProperties {

    private Boolean enabled = false;
    private Boolean continueOnError = false;
    /** Retained only to detect old environment configuration; no startup scripts execute. */
    private List<String> scripts = new ArrayList<>();
}
