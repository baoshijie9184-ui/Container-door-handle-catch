package com.ruanzhu.doorhandle.contracts.agent;

/** 运行中控制，仅服务端可提供身份；暂停发生在安全切点。 */
public interface AgentConversationControlApi {
    record View(String sessionId,String runId,String phase,long revision,boolean local,String text) {}
    View inspect(AgentActor actor,String sessionId);
    View command(AgentActor actor,String sessionId,String runId,String action,long expectedRevision);
    default int maxRunSeconds(){return 1800;}
}
