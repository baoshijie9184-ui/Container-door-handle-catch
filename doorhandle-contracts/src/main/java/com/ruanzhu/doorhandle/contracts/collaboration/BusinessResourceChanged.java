package com.ruanzhu.doorhandle.contracts.collaboration;

import java.time.Instant;

/** Published inside the mutation transaction; consumers send only AFTER_COMMIT. No field values or credentials. */
public record BusinessResourceChanged(String eventId, String auditId, String scope, String domain,
        String resourceType, String resourceId, String resourceVersion, String action, String requestId,
        long actorUserId, Instant occurredAt) { }
