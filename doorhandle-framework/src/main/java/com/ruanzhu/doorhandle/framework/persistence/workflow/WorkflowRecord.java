package com.ruanzhu.doorhandle.framework.persistence.workflow;

import java.time.LocalDateTime;
import java.time.LocalDate;
import com.ruanzhu.doorhandle.common.time.LegacyClockEvidence;

public record WorkflowRecord(long id, String workflowId, WorkflowKind kind, String idempotencyScope,
        String requestId, String requestSha256, long ownerUserId, Long actorUserId, Long parentWorkflowId,
        String resourceType, String resourceId, Long resourceRevision, String sessionId, String runId,
        String status, long revision, long fence, Integer activeSlot, String claimToken,
        LocalDateTime leaseExpiresAt, LocalDateTime expiresAt, int payloadVersion, String payloadJson,
        String resultJson, LocalDateTime createdAt, LocalDateTime updatedAt, LocalDateTime finishedAt,
        String resultSha256, String errorCode, LocalDate effectiveDate, LocalDateTime scheduledFor,
        LegacyClockEvidence legacyClockEvidence) {
    public boolean legacyClockUnresolved() { return legacyClockEvidence != null; }
    public WorkflowRecord(long id, String workflowId, WorkflowKind kind, String idempotencyScope,
        String requestId, String requestSha256, long ownerUserId, Long actorUserId, Long parentWorkflowId,
        String resourceType, String resourceId, Long resourceRevision, String sessionId, String runId,
        String status, long revision, long fence, Integer activeSlot, String claimToken,
        LocalDateTime leaseExpiresAt, LocalDateTime expiresAt, int payloadVersion, String payloadJson,
        String resultJson, LocalDateTime createdAt, LocalDateTime updatedAt, LocalDateTime finishedAt,
        String resultSha256, String errorCode, LocalDate effectiveDate, LocalDateTime scheduledFor) {
        this(id,workflowId,kind,idempotencyScope,requestId,requestSha256,ownerUserId,actorUserId,parentWorkflowId,
            resourceType,resourceId,resourceRevision,sessionId,runId,status,revision,fence,activeSlot,claimToken,
            leaseExpiresAt,expiresAt,payloadVersion,payloadJson,resultJson,createdAt,updatedAt,finishedAt,
            resultSha256,errorCode,effectiveDate,scheduledFor,null);
    }
}
