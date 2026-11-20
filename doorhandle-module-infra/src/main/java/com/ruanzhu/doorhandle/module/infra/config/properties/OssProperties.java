package com.ruanzhu.doorhandle.module.infra.config.properties;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Getter
@Setter
@Configuration
@ConfigurationProperties(prefix = "aliyun.oss")
public class OssProperties extends OssConnectionProperties {
    private OssConnectionProperties preview;
    private Integer uploadUrlExpireMinutes = 15;
    private Integer previewUrlExpireMinutes = 30;
    private String writePrefix;
    private String basePrefix = "detection";
}
