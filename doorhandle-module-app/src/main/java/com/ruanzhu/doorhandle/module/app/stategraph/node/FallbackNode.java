package com.ruanzhu.doorhandle.module.app.stategraph.node;

import com.ruanzhu.doorhandle.module.app.stategraph.core.AgentState;
import com.ruanzhu.doorhandle.module.app.stategraph.core.Node;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

/**
 * Fallback 节点 — 所有错误和异常的统一兜底处理。
 */
@Slf4j
@Component
public class FallbackNode implements Node {

    @Override
    public AgentState execute(AgentState state) {
        String error = state.getString(AgentState.KEY_ERROR);
        String guardReason = state.getString(AgentState.KEY_GUARD_REASON);
        Integer iteration = state.getInt(AgentState.KEY_ITERATION);
        log.warn("FallbackNode: 进入兜底, error={}, guardReason={}, iteration={}", error, guardReason, iteration);

        if (guardReason != null) {
            state.set(AgentState.KEY_RESULT_CONTENT,
                    "智能体流程已保护性中断，避免继续重复执行。原因：" + guardReason
                            + "。建议您换一种更明确的描述，或稍后从当前页面重新发起操作。");
        } else {
            state.set(AgentState.KEY_RESULT_CONTENT,
                    "抱歉，处理您的请求时遇到了问题，我不会基于不完整信息编造结果。请稍后重试，或补充任务编号、工单号、批次号、页面名称等关键信息后再问。");
        }
        state.set(AgentState.KEY_RESULT_TYPE, "TEXT");
        state.set(AgentState.KEY_INTENT, "FALLBACK");
        if (state.getString(AgentState.KEY_EXIT_REASON) == null) {
            state.set(AgentState.KEY_EXIT_REASON, AgentState.EXIT_COMPLETE);
        }
        return state;
    }
}
