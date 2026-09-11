package com.ruanzhu.doorhandle.module.infra.service;

import java.io.InputStream;
import java.net.URL;
import java.time.Duration;

public interface OssStorageService {
    URL generatePutUrl(String objectKey, String contentType, Duration duration);

    URL generateGetUrl(String objectKey, Duration duration);

    String getBucketName();

    String normalizeBasePrefix();

    boolean isConfigured();

    /** 使用 OSS SDK 直接上传文件内容，利用 SDK 内置的连接池和重试机制 */
    void putObject(String objectKey, InputStream content, long contentLength, String contentType);
}
