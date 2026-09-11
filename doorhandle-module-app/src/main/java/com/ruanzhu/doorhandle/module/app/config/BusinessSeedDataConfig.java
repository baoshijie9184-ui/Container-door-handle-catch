package com.ruanzhu.doorhandle.module.app.config;

import com.ruanzhu.doorhandle.module.app.config.properties.BusinessSeedDataProperties;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.Resource;
import org.springframework.core.io.ResourceLoader;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;

import javax.sql.DataSource;
import java.nio.charset.StandardCharsets;

@Configuration
@RequiredArgsConstructor
@Slf4j
public class BusinessSeedDataConfig {

    private final DataSource dataSource;
    private final ResourceLoader resourceLoader;
    private final BusinessSeedDataProperties properties;

    @Bean
    @ConditionalOnProperty(prefix = "app.business-seed", name = "enabled", havingValue = "true")
    public CommandLineRunner importBusinessSeedData() {
        return args -> {
            ResourceDatabasePopulator populator = new ResourceDatabasePopulator();
            populator.setSqlScriptEncoding(StandardCharsets.UTF_8.name());
            populator.setContinueOnError(Boolean.TRUE.equals(properties.getContinueOnError()));

            for (String scriptLocation : properties.getScripts()) {
                Resource script = resourceLoader.getResource(scriptLocation);
                if (!script.exists()) {
                    throw new IllegalStateException("业务预置数据脚本不存在: " + scriptLocation);
                }
                populator.addScript(script);
                log.info("已加入业务预置数据脚本: {}", scriptLocation);
            }

            log.info("开始导入业务预置数据，共 {} 个脚本", properties.getScripts().size());
            populator.execute(dataSource);
            log.info("业务预置数据导入完成");
        };
    }
}
