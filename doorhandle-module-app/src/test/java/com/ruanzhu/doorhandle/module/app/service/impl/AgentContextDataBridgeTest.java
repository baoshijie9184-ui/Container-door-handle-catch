package com.ruanzhu.doorhandle.module.app.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.agent.AgentCards;
import com.ruanzhu.doorhandle.contracts.agent.AgentContextDataApi;
import com.ruanzhu.doorhandle.contracts.agent.DetectionAgentReadApi;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AgentContextDataBridgeTest {
    @Test
    @SuppressWarnings("unchecked")
    void recentHistoryUsesTheFixedCutAndChecksTheCurrentTaskPermission() throws Exception {
        var actor = new AgentActor(28, "DET-0001", AgentActor.Role.INSPECTOR);
        var jdbc = mock(JdbcTemplate.class);
        var workspace = mock(AgentWorkspaceService.class);
        var tasks = mock(DetectionAgentReadApi.class);
        ObjectProvider<DetectionAgentReadApi> taskProvider = mock(ObjectProvider.class);
        when(taskProvider.getObject()).thenReturn(tasks);
        when(tasks.task(actor, "withdrawn-task")).thenThrow(new SecurityException("任务已撤权"));
        var json = new ObjectMapper();
        String card = json.writeValueAsString(new AgentCards.Envelope(1, "以前可访问的业务内容", "original-run",
                List.of(new AgentCards.Reference("TASKS", "get_task_detail", List.of("withdrawn-task"), null))));
        String sql = "SELECT id,role,message_type,content FROM chat_message WHERE session_id=? AND id<=? ORDER BY id DESC LIMIT ?";
        when(jdbc.queryForList(sql, "session", 12L, 3)).thenReturn(List.of(
                Map.of("id", 12L, "role", "assistant", "message_type", "AGENT_CARDS", "content", card),
                Map.of("id", 11L, "role", "user", "message_type", "TEXT", "content", "用户问题"),
                Map.of("id", 10L, "role", "user", "message_type", "TEXT", "content", "历史前缀")));
        var bridge = new AgentContextDataBridge(workspace, jdbc, json, taskProvider, null, null, null);

        var history = bridge.recentHistory(actor, "session", 12L, 2);

        assertThat(history.throughId()).isEqualTo(12L);
        assertThat(history.hasMore()).isTrue();
        assertThat(history.messages()).extracting(AgentContextDataApi.Message::id).containsExactly(11L, 12L);
        assertThat(history.messages().get(0).text()).isEqualTo("用户问题");
        assertThat(history.messages().get(1).text()).contains("访问范围已变化").doesNotContain("以前可访问");
        assertThat(history.messages().get(1).sources()).isEmpty();
        verify(tasks).task(actor, "withdrawn-task");
    }
}
