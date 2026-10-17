package com.ruanzhu.doorhandle.module.app.config.properties;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

import java.util.List;

@Data
@Configuration
@ConfigurationProperties(prefix = "app.cors")
public class AppCorsProperties {

    private List<String> allowedOrigins = List.of(
            "http://localhost:3001",
            "http://127.0.0.1:3001",
            "http://localhost:3002",
            "http://127.0.0.1:3002",
            "http://localhost:3003",
            "http://127.0.0.1:3003",
            "http://localhost:3004",
            "http://127.0.0.1:3004",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8080"
    );

    private List<String> allowedMethods = List.of("GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD");

    private List<String> allowedHeaders = List.of("*");

    private List<String> exposedHeaders = List.of("Authorization", "Content-Type", "X-Content-SHA256", "X-Export-Id", "Retry-After");

    private Boolean allowCredentials = true;

    private Long maxAge = 3600L;
}
