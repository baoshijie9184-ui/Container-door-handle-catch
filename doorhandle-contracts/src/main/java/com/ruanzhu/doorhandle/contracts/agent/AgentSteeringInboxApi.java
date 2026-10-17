package com.ruanzhu.doorhandle.contracts.agent;
import java.util.List;
/** 由会话模块持久化并授权交付补充要求，正文不进入运行元数据日志。 */
public interface AgentSteeringInboxApi {
    record Input(String id,String content) {}
    List<Input> take(AgentActor actor,String sessionId,String runId);
}
