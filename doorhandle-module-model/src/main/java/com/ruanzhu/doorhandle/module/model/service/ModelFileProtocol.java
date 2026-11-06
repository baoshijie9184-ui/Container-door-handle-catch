package com.ruanzhu.doorhandle.module.model.service;

import com.ruanzhu.doorhandle.framework.persistence.workflow.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.HexFormat;
import java.util.Map;
import java.util.Set;

/** Fixed file facts; SQL exposes and constrains path, digest, size and signed model identity. */
final class ModelFileProtocol {
    static final String UPLOAD_PREFIX="model-file:",RETENTION_PREFIX="model-retain:";
    record UploadV1(String storagePath,String pathSha256,String contentSha256,Long byteSize,Integer modelId,
                    String legacyCreatedAt,String legacyUpdatedAt) {
        UploadV1 {
            path(storagePath,pathSha256);digest(contentSha256);
            if(byteSize!=null&&byteSize<0)throw new IllegalArgumentException("模型文件长度无效");
            legacyTimes(legacyCreatedAt,legacyUpdatedAt);
        }
        UploadV1 ready(String hash,long bytes){return new UploadV1(storagePath,pathSha256,hash,bytes,null,legacyCreatedAt,legacyUpdatedAt);}
        UploadV1 registered(int model){return new UploadV1(storagePath,pathSha256,contentSha256,byteSize,model,legacyCreatedAt,legacyUpdatedAt);}
    }
    record RetentionV1(String retentionId,String fileId,String storagePath,String pathSha256,String updatedAtUtc,
                       String legacyCreatedAt,String legacyUpdatedAt) {
        RetentionV1 {
            identity(retentionId);if(fileId!=null)identity(fileId);path(storagePath,pathSha256);
            if(updatedAtUtc==null)throw new IllegalArgumentException("文件保留更新时间缺失");
            LocalDateTime.parse(updatedAtUtc);legacyTimes(legacyCreatedAt,legacyUpdatedAt);
        }
    }
    static WorkflowProtocols protocols() {
        return WorkflowProtocols.defaults().with(new WorkflowProtocol<>(WorkflowKind.MODEL_FILE_UPLOAD,1,UploadV1.class,
                Set.of("RESERVED"),Set.of("RETAINED"),Map.of("RESERVED",Set.of("FILE_READY"),
                "FILE_READY",Set.of("REGISTERED"),"REGISTERED",Set.of("RETAINED")),value->{},false));
    }
    static String requestDigest(long actor,String fileId,String request,String pathHash) {
        if(actor<=0)throw new IllegalArgumentException("模型文件操作人无效");identity(fileId);request(request);digest(pathHash);
        return sha(actor+"\n"+fileId+"\n"+request+"\n"+pathHash);
    }
    static void identity(String value){if(value==null||!value.matches("[A-Za-z0-9_-]{1,36}"))throw new IllegalArgumentException("模型文件标识无效");}
    static void request(String value){if(value==null||!value.matches("[A-Za-z0-9_-]{1,128}"))throw new IllegalArgumentException("模型文件请求编号无效");}
    static void path(String value,String hash) {
        if(value==null||value.codePointCount(0,value.length())>2048||hash==null||!sha(value).equals(hash))
            throw new IllegalArgumentException("模型文件位置或摘要无效");
    }
    private static void digest(String value){if(value!=null&&!value.matches("[a-f0-9]{64}"))throw new IllegalArgumentException("模型文件内容摘要无效");}
    private static void legacyTimes(String created,String updated) {
        if((created==null)!=(updated==null))throw new IllegalArgumentException("原模型文件时间证据不完整");
        if(created!=null){LocalDateTime.parse(created);LocalDateTime.parse(updated);}
    }
    static String sha(String value) {
        try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}
        catch(java.security.NoSuchAlgorithmException impossible){throw new IllegalStateException(impossible);}
    }
}
