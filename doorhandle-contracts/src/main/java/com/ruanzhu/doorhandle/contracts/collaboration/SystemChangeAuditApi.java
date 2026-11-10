package com.ruanzhu.doorhandle.contracts.collaboration;

import java.util.List;

/**
 * Internal automatic execution facts, never an HTTP/agent selectable actor type.
 * The owning module holds its row lock and writes state/revision in the same
 * transaction. No current login or initiator eligibility is required here.
 */
public interface SystemChangeAuditApi {
    enum Component { DETECTION_WORKER, IMAGE_DETECTION_ASYNC, IMAGE_DETECTION }

    /** Historical request initiator, independent of the actual system executor. */
    record Initiator(Long userId, String username) {
        public Initiator {
            if (userId != null && userId <= 0 || username != null && (username.isBlank() || username.length() > 128))
                throw new IllegalArgumentException("Invalid historical initiator");
            if (userId == null && username == null) throw new IllegalArgumentException("Empty historical initiator");
        }
    }

    /** Enterprise scope/APPLIED result are fixed by this server-only port. */
    record Event(Component component, String sourceEventId, Initiator initiator,
                 String domain, String resourceType, String resourceId, String action, String requestId,
                 Long beforeVersion, Long afterVersion, List<ChangeHistory.Change> changes) {
        public Event {
            if (component == null || sourceEventId == null || requestId == null)
                throw new IllegalArgumentException("System execution identity is required");
            changes = List.copyOf(changes);
        }
    }

    /** Required audit failure aborts the owning business transaction. */
    void appendSystemChange(Event event);
}
