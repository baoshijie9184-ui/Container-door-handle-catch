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
    private OSS approvedWriteClient;

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
        log.info("OSS upload authorization issued, contentType={}",contentType);
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
    @Override public byte[] readObject(String objectKey,long maxBytes){
        ensureConfigured();if(objectKey==null||objectKey.isBlank()||objectKey.length()>1024||objectKey.chars().anyMatch(Character::isISOControl)||maxBytes<1||maxBytes>26214400)throw new IllegalArgumentException("对象读取范围无效");
        try(var object=getClient().getObject(ossProperties.getBucketName(),objectKey)){
            if(object.getObjectMetadata().getContentLength()<1||object.getObjectMetadata().getContentLength()>maxBytes){object.forcedClose();throw new BusinessException("图片大小超出读取限制");}
            byte[] bytes=object.getObjectContent().readNBytes(Math.toIntExact(maxBytes+1));
            if(bytes.length<1||bytes.length>maxBytes||bytes.length!=object.getObjectMetadata().getContentLength())throw new BusinessException("图片长度无法核对");return bytes;
        }catch(java.io.IOException error){throw new BusinessException("业务图片内容暂不可读取");}
    }
    @Override public PutReceipt putApprovedObject(String objectKey,InputStream content,long contentLength,String contentType,String commandId,String fileId,String sha256){
        ensureConfigured();
        if(objectKey==null||objectKey.isBlank()||objectKey.length()>1024||objectKey.chars().anyMatch(Character::isISOControl)||contentLength<1||contentLength>26214400||commandId==null||!commandId.matches("[a-f0-9-]{36}")||fileId==null||!fileId.matches("[a-f0-9-]{36}")||sha256==null||!sha256.matches("[a-f0-9]{64}"))throw new IllegalArgumentException("批准上传参数无效");
        var metadata=new ObjectMetadata();metadata.setContentLength(contentLength);metadata.setContentType(contentType);
        metadata.setHeader("x-oss-forbid-overwrite","true");metadata.addUserMetadata("doorhandle-command",commandId);metadata.addUserMetadata("doorhandle-file",fileId);metadata.addUserMetadata("doorhandle-sha256",sha256);
        var result=approvedWriteClient().putObject(new PutObjectRequest(ossProperties.getBucketName(),objectKey,content,metadata));
        if(result==null)throw new BusinessException("批准上传没有可核实回执");return new PutReceipt(result.getETag(),result.getVersionId(),result.getRequestId());
    }
    @Override public ApprovedObject inspectApprovedObject(String objectKey,long maxBytes){
        ensureConfigured();if(objectKey==null||objectKey.isBlank()||objectKey.length()>1024||objectKey.chars().anyMatch(Character::isISOControl)||maxBytes<1||maxBytes>26214400)throw new IllegalArgumentException("对象核对范围无效");
        try(var object=approvedWriteClient().getObject(ossProperties.getBucketName(),objectKey)){
            var metadata=object.getObjectMetadata();long length=metadata.getContentLength();
            if(length<1||length>maxBytes){object.forcedClose();return new ApprovedObject("MISMATCH",length,null,null,null,null,null,null,null,object.getRequestId());}
            byte[] bytes=object.getObjectContent().readNBytes(Math.toIntExact(maxBytes+1));
            if(bytes.length!=length||bytes.length>maxBytes)throw new BusinessException("对象内容读取未完成");
            String digest=java.util.HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(bytes));
            var custom=metadata.getUserMetadata();return new ApprovedObject("READ",length,digest,metadata.getContentType(),custom.get("doorhandle-command"),custom.get("doorhandle-file"),custom.get("doorhandle-sha256"),metadata.getETag(),metadata.getVersionId(),object.getRequestId());
        }catch(com.aliyun.oss.OSSException error){if("NoSuchKey".equals(error.getErrorCode()))return new ApprovedObject("MISSING",0,null,null,null,null,null,null,null,null);throw new BusinessException("对象核对暂不可用");}
        catch(java.io.IOException|java.security.NoSuchAlgorithmException error){throw new BusinessException("对象内容核对未完成");}
    }
    private synchronized OSS approvedWriteClient(){
        if(approvedWriteClient==null){var config=new com.aliyun.oss.ClientBuilderConfiguration();config.setMaxErrorRetry(0);config.setConnectionTimeout(5000);config.setConnectionRequestTimeout(5000);config.setSocketTimeout(15000);config.setRequestTimeoutEnabled(true);config.setRequestTimeout(60000);
            approvedWriteClient=new OSSClientBuilder().build(ossProperties.getEndpoint(),ossProperties.getAccessKeyId(),ossProperties.getAccessKeySecret(),config);
        }return approvedWriteClient;
    }

    @PreDestroy
    public void shutdown() {
        if (ossClient != null) {
            ossClient.shutdown();
        }
        if(approvedWriteClient!=null)approvedWriteClient.shutdown();
    }

    private void ensureConfigured() {
        if (!isConfigured()) {
            throw new BusinessException("阿里云 OSS 配置不完整，无法生成上传或预览地址");
        }
    }

    private synchronized OSS getClient() {
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
