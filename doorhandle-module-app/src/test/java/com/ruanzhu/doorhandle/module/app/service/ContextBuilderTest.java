package com.ruanzhu.doorhandle.module.app.service;

import com.ruanzhu.doorhandle.module.app.stategraph.core.AgentState;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ContextBuilderTest {

    @Test
    void buildContextIncludesCurrentPageContext() {
        ContextBuilder contextBuilder = new ContextBuilder();
        AgentState state = AgentState.create("session-1", "这个页面下一步怎么做", "tester");
        state.set(AgentState.KEY_CURRENT_PAGE_TITLE, "模型管理");
        state.set(AgentState.KEY_CURRENT_ROUTE, "/models");

        String context = contextBuilder.buildContext(state, "这个页面下一步怎么做");

        assertThat(context).contains("[Current Page] 模型管理 (/models)");
        assertThat(context).contains("[Current User Input] 这个页面下一步怎么做");
    }
}
