package com.ruanzhu.doorhandle.module.model.entity;

import lombok.Data;

import java.time.LocalDateTime;

/** Read DTO for typed detection-model audit events; not a persistence table mapping. */
@Data
public class ModelOperationLog {

    private Long id;
    /** Original pre-migration ID when present; id remains the shared audit cursor. */
    private Long legacyId;

    private Integer modelId;

    private String operationType;

    private String operator;

    private LocalDateTime operationTime;

    private String remark;
}
