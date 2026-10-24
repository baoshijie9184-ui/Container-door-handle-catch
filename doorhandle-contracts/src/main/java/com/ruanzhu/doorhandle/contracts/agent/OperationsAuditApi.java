package com.ruanzhu.doorhandle.contracts.agent;

/** Metadata only; callers must never pass prompts, credentials or document contents. */
public interface OperationsAuditApi {
    record Event(AgentActor actor,String scope,String domain,String action,String resourceId,
                 String requestId,String result,Long resourceVersion) {}
    void append(Event event);
}
