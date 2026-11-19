package com.ruanzhu.doorhandle.module.infra.config.properties;

import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class OssConnectionProperties {
    private String endpoint;
    private String bucketName;
    private String accessKeyId;
    private String accessKeySecret;
    private String proxyHost;
    private int proxyPort;
}
