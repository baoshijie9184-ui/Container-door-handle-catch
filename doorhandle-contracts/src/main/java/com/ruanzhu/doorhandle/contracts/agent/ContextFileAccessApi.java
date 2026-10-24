package com.ruanzhu.doorhandle.contracts.agent;

/** App file delivery asks AI to reauthorize the private tool result's original business sources. */
public interface ContextFileAccessApi {
    void assertReadable(AgentActor actor,String session,String fileId);
}
