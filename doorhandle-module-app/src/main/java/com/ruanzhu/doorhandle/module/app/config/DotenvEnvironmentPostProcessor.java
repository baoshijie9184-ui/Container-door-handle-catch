package com.ruanzhu.doorhandle.module.app.config;

import io.github.cdimascio.dotenv.Dotenv;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.env.EnvironmentPostProcessor;
import org.springframework.core.env.ConfigurableEnvironment;
import org.springframework.core.env.MapPropertySource;

import java.util.HashMap;
import java.util.Map;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Load only an explicitly selected server file; never read the working directory .env.
 * DOORHANDLE_ENV_FILE belongs to Compose and is deliberately a different setting.
 */
@Slf4j
public class DotenvEnvironmentPostProcessor implements EnvironmentPostProcessor {

    @Override
    public void postProcessEnvironment(ConfigurableEnvironment environment, SpringApplication application) {
        String configured = environment.getProperty("DOORHANDLE_JAVA_ENV_FILE");
        if (configured == null || configured.isBlank()) return;
        Path file = Path.of(configured);
        if (!file.isAbsolute() || !Files.isRegularFile(file) || Files.isSymbolicLink(file)) {
            throw new IllegalStateException("DOORHANDLE_JAVA_ENV_FILE must select an existing absolute server environment file");
        }
        try {
            Dotenv dotenv = Dotenv.configure()
                    .directory(file.getParent().toString())
                    .filename(file.getFileName().toString())
                    .load();

            Map<String, Object> envMap = new HashMap<>();
            dotenv.entries().forEach(entry -> {
                envMap.put(entry.getKey(), entry.getValue());
            });

            addDotenvProperties(environment, envMap);

            log.info("已加载显式服务器环境文件，共 {} 个变量", envMap.size());
        } catch (Exception e) {
            // Parser failures can contain credentials. Do not expose their text or cause.
            throw new IllegalStateException("Unable to load DOORHANDLE_JAVA_ENV_FILE");
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
