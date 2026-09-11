package com.ruanzhu.doorhandle.module.app.stategraph.checkpoint;

import com.ruanzhu.doorhandle.module.app.stategraph.core.AgentState;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;

/**
 * StateGraph 持久化接口。
 * thread_id 等价于 chat_session.session_id，实现用户/会话隔离。
 */
public interface Checkpointer {

    void save(TenantContext tenant, String threadId, AgentState state);

    AgentState load(TenantContext tenant, String threadId);

    void delete(TenantContext tenant, String threadId);
}
