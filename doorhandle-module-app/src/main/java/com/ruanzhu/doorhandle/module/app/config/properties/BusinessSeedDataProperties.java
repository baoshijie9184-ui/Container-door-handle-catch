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
    private List<String> scripts = new ArrayList<>(List.of(
            "classpath:db/migration-V14-security-reliability-hardening.sql",
            "classpath:db/migration-V13-business-seed-data-normalization.sql",
            "classpath:db/business-seed-new-features.sql",
            "classpath:db/business-seed-more-features.sql",
            "classpath:db/business-seed-trace-rich.sql"
    ));
}
