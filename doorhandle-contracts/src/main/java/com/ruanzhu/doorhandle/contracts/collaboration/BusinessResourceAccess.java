package com.ruanzhu.doorhandle.contracts.collaboration;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;

/** Current domain authorization. Unsupported types deny; implementations must not trust the supplied role snapshot. */
public interface BusinessResourceAccess {
    boolean mayRead(AgentActor actor, String scope, String domain, String resourceType, String resourceId);
}
