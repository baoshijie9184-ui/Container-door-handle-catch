package com.ruanzhu.doorhandle.module.ai.agent;

import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Component;

/** AG-UI 与主站聊天共用单体进程的会话执行锁。 */
@Component
public class AgentRunRegistry {
    private final Set<String> active = ConcurrentHashMap.newKeySet();
    public static String key(com.ruanzhu.doorhandle.contracts.agent.AgentActor actor, String session) {
        return actor.userId() + ":" + RoleAgentCatalog.mainId(actor) + ":" + session;
    }
    public boolean isActive(com.ruanzhu.doorhandle.contracts.agent.AgentActor actor, String session) {
        return active.contains(key(actor, session));
    }
    public boolean acquire(String session) { return active.add(session); }
    public void release(String session) { active.remove(session); }
}
