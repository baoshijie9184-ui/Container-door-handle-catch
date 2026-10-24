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
    /** Internal object keys only; returns bounded bytes, never follows a caller-provided URL. */
    default byte[] readObject(String objectKey,long maxBytes){throw new UnsupportedOperationException("Bounded OSS read unavailable");}
    record PutReceipt(String etag,String versionId,String requestId) {}
    record ApprovedObject(String status,long bytes,String sha256,String contentType,String commandId,String fileId,
                          String declaredSha256,String etag,String versionId,String requestId) {}
    /** Reads and hashes bounded real bytes. Metadata and ETag alone are not content evidence. */
    default ApprovedObject inspectApprovedObject(String objectKey,long maxBytes){throw new UnsupportedOperationException("Approved OSS inspection unavailable");}
    /** Approved command writes disable SDK error retries and never accept arbitrary object destinations from the model. */
    default PutReceipt putApprovedObject(String objectKey,InputStream content,long contentLength,String contentType,String commandId,String fileId,String sha256){throw new UnsupportedOperationException("Approved one-attempt OSS writes unavailable");}
}
