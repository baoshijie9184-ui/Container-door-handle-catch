package com.ruanzhu.doorhandle.framework.persistence.workflow;

import java.time.LocalDateTime;

/** Immutable event envelope. Payload is a versioned record, never an unregistered map. */
public record AuditEvent(String kind, Long ownerUserId, Long actorUserId, String resourceType,
        String resourceId, String sessionId, String runId, Long sequenceNo, String requestId,
        String action, Long revision, String contentSha256, LocalDateTime occurredAt,
        int payloadVersion, Object payload) { }
