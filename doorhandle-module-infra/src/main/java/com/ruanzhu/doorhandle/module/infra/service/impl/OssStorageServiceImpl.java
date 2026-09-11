package com.ruanzhu.doorhandle.module.infra.service.impl;

import com.aliyun.oss.HttpMethod;
import com.aliyun.oss.OSS;
import com.aliyun.oss.OSSClientBuilder;
import com.aliyun.oss.model.GeneratePresignedUrlRequest;
import com.aliyun.oss.model.ObjectMetadata;
import com.aliyun.oss.model.PutObjectRequest;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.infra.config.properties.OssProperties;
import com.ruanzhu.doorhandle.module.infra.service.OssStorageService;
import jakarta.annotation.PreDestroy;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.io.InputStream;
import java.net.URL;
import java.time.Duration;
import java.util.Date;

@Service
@RequiredArgsConstructor
@Slf4j
public class OssStorageServiceImpl implements OssStorageService {

    private final OssProperties ossProperties;
    private OSS ossClient;

    @Override
    public URL generatePutUrl(String objectKey, String contentType, Duration duration) {
        ensureConfigured();
        GeneratePresignedUrlRequest request = new GeneratePresignedUrlRequest(
                ossProperties.getBucketName(),
                objectKey,
                HttpMethod.PUT
        );
        request.setExpiration(new Date(System.currentTimeMillis() + duration.toMillis()));
        if (org.springframework.util.StringUtils.hasText(contentType)) {
            request.setContentType(contentType);
        }
        URL url = getClient().generatePresignedUrl(request);
        log.info("OSS PUT URL: bucket={}, endpoint={}, contentType={}, url={}",
                ossProperties.getBucketName(), ossProperties.getEndpoint(), contentType, url);
        return url;
    }

    @Override
    public URL generateGetUrl(String objectKey, Duration duration) {
        ensureConfigured();
        GeneratePresignedUrlRequest request = new GeneratePresignedUrlRequest(
                ossProperties.getBucketName(),
                objectKey,
                HttpMethod.GET
        );
        request.setExpiration(new Date(System.currentTimeMillis() + duration.toMillis()));
        return getClient().generatePresignedUrl(request);
    }

    @Override
    public String getBucketName() {
        return ossProperties.getBucketName();
    }

    @Override
    public String normalizeBasePrefix() {
        String prefix = StringUtils.hasText(ossProperties.getBasePrefix()) ? ossProperties.getBasePrefix().trim() : "detection";
        prefix = prefix.replace("\\", "/");
        prefix = prefix.replaceAll("^/+", "");
        prefix = prefix.replaceAll("/+$", "");
        return prefix;
    }

    @Override
    public boolean isConfigured() {
        return StringUtils.hasText(ossProperties.getEndpoint())
                && StringUtils.hasText(ossProperties.getBucketName())
                && StringUtils.hasText(ossProperties.getAccessKeyId())
                && StringUtils.hasText(ossProperties.getAccessKeySecret());
    }

    @Override
    public void putObject(String objectKey, InputStream content, long contentLength, String contentType) {
        ensureConfigured();
        ObjectMetadata metadata = new ObjectMetadata();
        metadata.setContentLength(contentLength);
        if (org.springframework.util.StringUtils.hasText(contentType)) {
            metadata.setContentType(contentType);
        }
        PutObjectRequest request = new PutObjectRequest(ossProperties.getBucketName(), objectKey, content, metadata);
        getClient().putObject(request);
    }

    @PreDestroy
    public void shutdown() {
        if (ossClient != null) {
            ossClient.shutdown();
        }
    }

    private void ensureConfigured() {
        if (!isConfigured()) {
            throw new BusinessException("阿里云 OSS 配置不完整，无法生成上传或预览地址");
        }
    }

    private OSS getClient() {
        if (ossClient == null) {
            ossClient = new OSSClientBuilder().build(
                    ossProperties.getEndpoint(),
                    ossProperties.getAccessKeyId(),
                    ossProperties.getAccessKeySecret()
            );
        }
        return ossClient;
    }
}
