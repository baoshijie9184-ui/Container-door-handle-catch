package com.ruanzhu.doorhandle.framework.persistence.workflow;

import java.time.LocalDateTime;
import java.time.LocalDate;

public record WorkflowRecord(long id, String workflowId, WorkflowKind kind, String idempotencyScope,
        String requestId, String requestSha256, long ownerUserId, Long actorUserId, Long parentWorkflowId,
        String resourceType, String resourceId, Long resourceRevision, String sessionId, String runId,
        String status, long revision, long fence, Integer activeSlot, String claimToken,
        LocalDateTime leaseExpiresAt, LocalDateTime expiresAt, int payloadVersion, String payloadJson,
        String resultJson, LocalDateTime createdAt, LocalDateTime updatedAt, LocalDateTime finishedAt,
        String resultSha256, String errorCode, LocalDate effectiveDate, LocalDateTime scheduledFor) { }
