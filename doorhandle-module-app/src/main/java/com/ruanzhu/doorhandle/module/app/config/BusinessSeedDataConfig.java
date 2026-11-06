package com.ruanzhu.doorhandle.module.app.config;

import com.ruanzhu.doorhandle.module.app.config.properties.BusinessSeedDataProperties;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
@RequiredArgsConstructor
public class BusinessSeedDataConfig {
    private final BusinessSeedDataProperties properties;

    @Bean
    @ConditionalOnProperty(prefix = "app.business-seed", name = "enabled", havingValue = "true")
    public CommandLineRunner importBusinessSeedData() {
        return args -> {
            // The V13-V15 startup importer predates the compact schema. Even an explicit
            // legacy scripts override must not recreate retired tables or seed identities.
            throw new IllegalStateException("APP_BUSINESS_SEED_ENABLED 已退役，请保持关闭；新库初始化及旧数据迁移必须通过经过核验的 compact 迁移入口执行");
        };
    }
}
