package com.ruanzhu.doorhandle.module.app.stategraph.node;

import com.ruanzhu.doorhandle.module.app.dto.chat.AgentExecutionResult;
import com.ruanzhu.doorhandle.module.app.service.agent.ReportAgentService;
import com.ruanzhu.doorhandle.module.app.stategraph.core.AgentState;
import com.ruanzhu.doorhandle.module.app.stategraph.core.Node;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.function.Consumer;

/**
 * 报表统计 Agent 节点，包装 ReportAgentService。
 */
@Component
@RequiredArgsConstructor
public class ReportAgentNode implements Node {

    private final ReportAgentService reportAgentService;

    @Override
    public AgentState execute(AgentState state) {
        String prompt = state.getString(AgentState.KEY_USER_INPUT);
        String ragContext = state.getString(AgentState.KEY_RAG_CONTEXT);
        String username = state.getString(AgentState.KEY_USERNAME);
        Boolean confirmed = state.getBool(AgentState.KEY_CONFIRMED);
        Consumer<String> tokenConsumer = state.get(AgentState.KEY_STREAM_CONSUMER, Consumer.class);

        AgentExecutionResult result;
        if (Boolean.TRUE.equals(confirmed)) {
            result = reportAgentService.executeConfirmedAction(prompt, username);
        } else {
            result = reportAgentService.answer(enrichPromptWithRagContext(prompt, ragContext), username, tokenConsumer);
        }

        state.set(AgentState.KEY_RESULT_CONTENT, result.getContent());
        state.set(AgentState.KEY_RESULT_TYPE, result.getMessageType());
        state.set(AgentState.KEY_INTENT, result.getIntent());
        state.set(AgentState.KEY_EXIT_REASON, AgentState.EXIT_COMPLETE);
        return state;
    }

    private String enrichPromptWithRagContext(String prompt, String ragContext) {
        if (ragContext == null || ragContext.isBlank()) {
            return prompt;
        }
        return (prompt == null ? "" : prompt)
                + "\n\n以下是 RAG 检索到的系统知识库片段。请优先参考这些片段和实时业务数据回答；"
                + "如果片段没有覆盖用户问题，必须明确说明“知识库没有找到足够依据”，不要编造页面、状态、数量或操作结果。\n"
                + ragContext;
    }
}
