package com.ruanzhu.doorhandle.module.infra.service;

import com.aliyun.oss.ClientBuilderConfiguration;
import com.aliyun.oss.HttpMethod;
import com.aliyun.oss.OSS;
import com.aliyun.oss.OSSClientBuilder;
import com.aliyun.oss.model.GeneratePresignedUrlRequest;
import com.aliyun.oss.model.GetObjectRequest;
import com.aliyun.oss.model.OSSObject;
import com.ruanzhu.doorhandle.module.infra.config.properties.OssProperties;
import com.ruanzhu.doorhandle.module.infra.config.properties.OssConnectionProperties;
import jakarta.annotation.PreDestroy;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.net.URL;
import java.time.Duration;
import java.time.Instant;
import java.util.Date;

/** Optional private credentials for historical reads. Uploads keep their own configuration. */
@Service
public class OssPreviewStorage {
    private final OssConnectionProperties settings;
    private OSS client;

    public OssPreviewStorage(OssProperties properties) {
        settings = properties.getPreview() == null ? properties : properties.getPreview();
    }

    public boolean configured() {
        return StringUtils.hasText(settings.getBucketName()) && StringUtils.hasText(settings.getEndpoint())
                && !settings.getEndpoint().endsWith(".invalid") && StringUtils.hasText(settings.getAccessKeyId())
                && StringUtils.hasText(settings.getAccessKeySecret());
    }

    private synchronized OSS client() {
        if (!configured()) throw new IllegalStateException("OSS 预览未配置");
        if (client == null) {
            var config = new ClientBuilderConfiguration();
            config.setMaxErrorRetry(0);
            config.setConnectionTimeout(5000);
            config.setConnectionRequestTimeout(5000);
            config.setSocketTimeout(15000);
            if (StringUtils.hasText(settings.getProxyHost())) {
                config.setProxyHost(settings.getProxyHost());
                config.setProxyPort(settings.getProxyPort());
            }
            client = new OSSClientBuilder().build(settings.getEndpoint(), settings.getAccessKeyId(), settings.getAccessKeySecret(), config);
        }
        return client;
    }

    public URL sign(String key, Duration validity) {
        var request = new GeneratePresignedUrlRequest(settings.getBucketName(), key, HttpMethod.GET);
        request.setExpiration(Date.from(Instant.now().plus(validity)));
        return client().generatePresignedUrl(request);
    }

    public OSSObject open(String key, boolean probe) {
        var request = new GetObjectRequest(settings.getBucketName(), key);
        if (probe) request.setRange(0, 0);
        return client().getObject(request);
    }

    @PreDestroy
    public synchronized void close() {
        if (client != null) client.shutdown();
    }
}
