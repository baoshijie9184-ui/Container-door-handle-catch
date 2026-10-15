package com.ruanzhu.doorhandle.module.app.dto.chat;

import com.ruanzhu.doorhandle.contracts.agent.AgentConversationApi;
import lombok.Data;
import java.util.List;

/** 最近一次真实 AgentScope 执行事件，不把历史 StateGraph 状态当作 SDK 轨迹。 */
@Data
public class ConversationTraceResponse {
    private String sessionId;
    private String framework = "AgentScope";
    private String runId;
    private String status;
    private String updatedAt;
    private List<AgentConversationApi.Event> events = List.of();
}
