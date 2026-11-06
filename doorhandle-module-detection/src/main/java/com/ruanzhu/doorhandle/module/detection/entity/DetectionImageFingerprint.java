package com.ruanzhu.doorhandle.module.detection.entity;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class DetectionImageFingerprint {
    /** Original fingerprint ID retained only as migration provenance, never a content/workflow primary key. */
    private Long id;
    private String sha256;
    private String fileName;
    private String objectKey;
    private String status;
    private String lastTaskId;
    private String ownerUserId;
    private Integer version;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
