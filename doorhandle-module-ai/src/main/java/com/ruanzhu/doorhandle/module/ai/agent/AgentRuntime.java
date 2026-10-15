package com.ruanzhu.doorhandle.module.ai.agent;

import io.agentscope.core.agent.Agent;
import io.agentscope.core.ReActAgent;
import io.agentscope.harness.agent.HarnessAgent;

public final class AgentRuntime {
    private AgentRuntime() {}
    public static void close(Agent agent) {
        if (agent instanceof HarnessAgent harness) harness.close();
        else if (agent instanceof ReActAgent react) react.close();
        else agent.interrupt();
    }
}
