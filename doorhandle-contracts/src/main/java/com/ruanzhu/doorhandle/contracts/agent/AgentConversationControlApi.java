package com.ruanzhu.doorhandle.contracts.agent;

/** 运行中控制，仅服务端可提供身份；暂停发生在安全切点。 */
public interface AgentConversationControlApi {
    record View(String sessionId,String runId,String phase,long revision,boolean local,String text) {}
    View inspect(AgentActor actor,String sessionId);
    View command(AgentActor actor,String sessionId,String runId,String action,long expectedRevision);
    /** Commit the authorized input while the addressed local agent can still accept it. */
    void guide(AgentActor actor, String sessionId, String runId,
               java.util.function.Supplier<AgentSteeringInboxApi.Input> accept);
    default int maxRunSeconds(){return 1800;}
}
