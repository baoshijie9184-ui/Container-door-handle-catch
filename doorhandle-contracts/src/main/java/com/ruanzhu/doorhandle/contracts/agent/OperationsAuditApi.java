package com.ruanzhu.doorhandle.contracts.agent;

/** Metadata only; callers must never pass prompts, credentials or document contents. */
public interface OperationsAuditApi {
    record Event(AgentActor actor,String scope,String domain,String action,String resourceId,
                 String requestId,String result,Long resourceVersion) {}
    record ChangeEvent(Event metadata, String resourceType, String displayName, Long beforeVersion,
            java.util.List<com.ruanzhu.doorhandle.contracts.collaboration.ChangeHistory.Change> changes) {
        public ChangeEvent { changes = java.util.List.copyOf(changes); }
    }
    record ChangeReceipt(String auditId, String eventId, String resourceVersion) { }
    void append(Event event);
    default void appendChange(ChangeEvent event) { throw new IllegalStateException("Versioned change audit is unavailable"); }
    default ChangeReceipt appendChangeWithReceipt(ChangeEvent event) { throw new IllegalStateException("Versioned change audit receipt is unavailable"); }
}
