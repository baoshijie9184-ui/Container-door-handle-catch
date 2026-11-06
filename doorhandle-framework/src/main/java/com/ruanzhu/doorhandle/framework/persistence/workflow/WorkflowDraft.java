package com.ruanzhu.doorhandle.framework.persistence.workflow;

import java.time.LocalDateTime;

/** New-operation envelope. The store validates identity, protocol, payload and transaction. */
public record WorkflowDraft(String workflowId, WorkflowKind kind, String idempotencyScope,
        String requestId, String requestSha256, long ownerUserId, Long actorUserId, Long parentWorkflowId,
        String resourceType, String resourceId, Long resourceRevision, String sessionId, String runId,
        String initialState, LocalDateTime expiresAt, int payloadVersion, Object payload) { }
