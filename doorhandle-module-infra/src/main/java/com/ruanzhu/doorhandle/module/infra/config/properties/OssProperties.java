package com.ruanzhu.doorhandle.module.infra.config.properties;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Data
@Configuration
@ConfigurationProperties(prefix = "aliyun.oss")
public class OssProperties {
    private String endpoint;
    private String bucketName;
    private String accessKeyId;
    private String accessKeySecret;
    private Integer uploadUrlExpireMinutes = 15;
    private Integer previewUrlExpireMinutes = 30;
    private String basePrefix = "detection";
}
