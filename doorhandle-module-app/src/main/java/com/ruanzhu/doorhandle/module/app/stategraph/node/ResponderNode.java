package com.ruanzhu.doorhandle.module.app.stategraph.node;

import com.ruanzhu.doorhandle.module.app.stategraph.core.AgentState;
import com.ruanzhu.doorhandle.module.app.stategraph.core.Node;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

/**
 * 终端响应节点 — 校验输出完整性，设置最终 exit_reason。
 */
@Slf4j
@Component
public class ResponderNode implements Node {

    @Override
    public AgentState execute(AgentState state) {
        String resultContent = state.getString(AgentState.KEY_RESULT_CONTENT);
        String resultType = state.getString(AgentState.KEY_RESULT_TYPE);

        if (!StringUtils.hasText(resultContent)) {
            log.warn("ResponderNode: result_content 为空，设置默认回复");
            state.set(AgentState.KEY_RESULT_CONTENT, "抱歉，当前没有足够上下文生成可靠回答。为避免误导，我不会编造结果；请补充任务编号、工单号、批次号或你所在页面后再试。");
            state.set(AgentState.KEY_RESULT_TYPE, "TEXT");
        }

        if (!StringUtils.hasText(resultType)) {
            state.set(AgentState.KEY_RESULT_TYPE, "TEXT");
        }

        state.set(AgentState.KEY_EXIT_REASON, AgentState.EXIT_COMPLETE);
        log.debug("ResponderNode: 响应已就绪, type={}, contentLength={}",
                state.getString(AgentState.KEY_RESULT_TYPE),
                state.getString(AgentState.KEY_RESULT_CONTENT).length());
        return state;
    }
}
