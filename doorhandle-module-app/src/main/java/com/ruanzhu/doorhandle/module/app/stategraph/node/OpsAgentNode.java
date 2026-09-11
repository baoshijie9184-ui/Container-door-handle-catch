package com.ruanzhu.doorhandle.module.app.stategraph.node;

import com.ruanzhu.doorhandle.module.app.dto.chat.AgentExecutionResult;
import com.ruanzhu.doorhandle.module.app.service.agent.OpsAgentService;
import com.ruanzhu.doorhandle.module.app.stategraph.core.AgentState;
import com.ruanzhu.doorhandle.module.app.stategraph.core.Node;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.function.Consumer;

/**
 * 系统运维 Agent 节点，包装 OpsAgentService。
 * OpsAgent 无 write 操作，始终调用 answer()。
 */
@Component
@RequiredArgsConstructor
public class OpsAgentNode implements Node {

    private final OpsAgentService opsAgentService;

    @Override
    public AgentState execute(AgentState state) {
        String prompt = state.getString(AgentState.KEY_USER_INPUT);
        String ragContext = state.getString(AgentState.KEY_RAG_CONTEXT);
        String username = state.getString(AgentState.KEY_USERNAME);
        String currentRoute = state.getString(AgentState.KEY_CURRENT_ROUTE);
        String currentPageTitle = state.getString(AgentState.KEY_CURRENT_PAGE_TITLE);
        Consumer<String> tokenConsumer = state.get(AgentState.KEY_STREAM_CONSUMER, Consumer.class);

        String enrichedPrompt = enrichPromptWithPageContext(prompt, currentRoute, currentPageTitle);
        enrichedPrompt = enrichPromptWithRagContext(enrichedPrompt, ragContext);
        AgentExecutionResult result = opsAgentService.answer(enrichedPrompt, username, tokenConsumer);

        state.set(AgentState.KEY_RESULT_CONTENT, result.getContent());
        state.set(AgentState.KEY_RESULT_TYPE, result.getMessageType());
        state.set(AgentState.KEY_INTENT, result.getIntent());
        state.set(AgentState.KEY_EXIT_REASON, AgentState.EXIT_COMPLETE);
        return state;
    }

    private String enrichPromptWithPageContext(String prompt, String currentRoute, String currentPageTitle) {
        if (!hasText(currentRoute) && !hasText(currentPageTitle)) {
            return prompt;
        }
        String text = prompt == null ? "" : prompt;
        String normalized = text.toLowerCase();
        boolean needsPageContext = normalized.contains("当前页面")
                || normalized.contains("这个页面")
                || normalized.contains("本页")
                || normalized.contains("下一步")
                || normalized.contains("怎么用")
                || normalized.contains("入口")
                || normalized.contains("页面");
        if (!needsPageContext) {
            return prompt;
        }
        StringBuilder sb = new StringBuilder(text);
        sb.append("\n\n当前页面上下文：");
        if (hasText(currentPageTitle)) {
            sb.append("页面标题=").append(currentPageTitle).append("；");
        }
        if (hasText(currentRoute)) {
            sb.append("路由=").append(currentRoute).append("；");
        }
        return sb.toString();
    }

    private boolean hasText(String value) {
        return value != null && !value.isBlank();
    }

    private String enrichPromptWithRagContext(String prompt, String ragContext) {
        if (!hasText(ragContext)) {
            return prompt;
        }
        return (prompt == null ? "" : prompt)
                + "\n\n以下是 RAG 检索到的系统知识库片段。请优先参考这些片段和实时业务数据回答；"
                + "如果片段没有覆盖用户问题，必须明确说明“知识库没有找到足够依据”，不要编造页面、状态、数量或操作结果。\n"
                + ragContext;
    }
}
