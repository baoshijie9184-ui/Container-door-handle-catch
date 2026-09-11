package com.ruanzhu.doorhandle.module.app.config;

import io.github.cdimascio.dotenv.Dotenv;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.env.EnvironmentPostProcessor;
import org.springframework.core.env.ConfigurableEnvironment;
import org.springframework.core.env.MapPropertySource;

import java.util.HashMap;
import java.util.Map;

/**
 * 在 Spring 环境准备阶段自动加载 .env 文件
 * 确保在属性绑定之前就设置好环境变量
 */
@Slf4j
public class DotenvEnvironmentPostProcessor implements EnvironmentPostProcessor {

    @Override
    public void postProcessEnvironment(ConfigurableEnvironment environment, SpringApplication application) {
        try {
            Dotenv dotenv = Dotenv.configure()
                    .directory(".")
                    .ignoreIfMalformed()
                    .ignoreIfMissing()
                    .load();

            Map<String, Object> envMap = new HashMap<>();
            dotenv.entries().forEach(entry -> {
                envMap.put(entry.getKey(), entry.getValue());
            });

            addDotenvProperties(environment, envMap);

            log.info("已加载 .env 文件，共 {} 个变量", envMap.size());
        } catch (Exception e) {
            log.warn("加载 .env 文件失败: {}", e.getMessage());
        }
    }

    static void addDotenvProperties(ConfigurableEnvironment environment, Map<String, Object> envMap) {
        if (envMap.isEmpty()) {
            return;
        }
        environment.getPropertySources()
                .addLast(new MapPropertySource("dotenvProperties", envMap));
    }
}
