package com.ruanzhu.doorhandle.module.app.service;

import com.ruanzhu.doorhandle.module.app.stategraph.core.AgentState;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 上下文组装服务 — 从 AgentState 中提取结构化信息，
 * 组装成 LLM 可理解的上下文 prompt，供 RouterNode、SlotFillingNode、各 Agent 统一使用。
 */
@Slf4j
@Service
public class ContextBuilder {

    @Value("${conversation.max-recent-messages:10}")
    private int maxRecentMessages;

    private static final String SYSTEM_PROMPT =
            "你是门把手检测系统的智能助手，负责帮助用户完成图片检测任务。\n"
                    + "你可以：上传本地图片文件夹进行批量检测、查询检测任务状态和结果、管理设备和人员信息。\n"
                    + "请用中文回答，语气简洁专业。";

    /** 组装完整的上下文 prompt */
    public String buildContext(AgentState state, String currentUserInput) {
        StringBuilder sb = new StringBuilder();

        sb.append("[System]\n").append(SYSTEM_PROMPT).append("\n\n");

        String currentRoute = state.getString(AgentState.KEY_CURRENT_ROUTE);
        String currentPageTitle = state.getString(AgentState.KEY_CURRENT_PAGE_TITLE);
        if (StringUtils.hasText(currentRoute) || StringUtils.hasText(currentPageTitle)) {
            sb.append("[Current Page] ");
            if (StringUtils.hasText(currentPageTitle)) {
                sb.append(currentPageTitle);
            }
            if (StringUtils.hasText(currentRoute)) {
                sb.append(" (").append(currentRoute).append(")");
            }
            sb.append("\n\n");
        }

        // 注入用户长期记忆
        String ragContext = state.getString(AgentState.KEY_RAG_CONTEXT);
        if (StringUtils.hasText(ragContext)) {
            sb.append(ragContext).append("\n\n");
        }

        // 注入用户长期记忆
        String memoryContext = state.getString("user_memory_context");
        if (StringUtils.hasText(memoryContext)) {
            sb.append(memoryContext).append("\n");
        }

        String summary = state.getString(AgentState.KEY_CONVERSATION_SUMMARY);
        if (StringUtils.hasText(summary)) {
            sb.append("[Conversation Summary]\n").append(summary).append("\n\n");
        }

        String taskType = state.getString(AgentState.KEY_TASK_TYPE);
        if (StringUtils.hasText(taskType)) {
            sb.append("[Current Task] ").append(taskType).append("\n");
        }

        Map<String, Object> slots = state.getSlots();
        if (slots != null && !slots.isEmpty()) {
            sb.append("[Filled Slots] ");
            sb.append(slots.entrySet().stream()
                    .map(e -> e.getKey() + "=" + e.getValue())
                    .collect(Collectors.joining(", ")));
            sb.append("\n");
        }

        List<String> missing = state.getMissingSlots();
        if (missing != null && !missing.isEmpty()) {
            sb.append("[Missing Slots] ").append(String.join(", ", missing)).append("\n");
        }

        List<Map<String, Object>> recentMsgs = state.getRecentMessages();
        if (recentMsgs != null && !recentMsgs.isEmpty()) {
            int start = Math.max(0, recentMsgs.size() - maxRecentMessages);
            sb.append("[Recent Messages]\n");
            for (int i = start; i < recentMsgs.size(); i++) {
                Map<String, Object> msg = recentMsgs.get(i);
                String role = String.valueOf(msg.getOrDefault("role", "unknown"));
                String content = String.valueOf(msg.getOrDefault("content", ""));
                sb.append("  [").append(role).append("] ").append(content).append("\n");
            }
            sb.append("\n");
        }

        if (StringUtils.hasText(currentUserInput)) {
            sb.append("[Current User Input] ").append(currentUserInput).append("\n");
        }

        return sb.toString();
    }

    /** 仅返回系统 prompt（用于简单场景） */
    public String getSystemPrompt() {
        return SYSTEM_PROMPT;
    }
}
