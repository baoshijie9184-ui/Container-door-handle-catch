package com.ruanzhu.doorhandle.module.app.stategraph.checkpoint;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.app.mapper.ChatSessionMapper;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import com.ruanzhu.doorhandle.module.app.stategraph.core.AgentState;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import java.util.Arrays;
import java.util.Set;

class MySqlCheckpointerTest {

    @Test
    void exposesNoUnscopedCheckpointOperations() {
        assertThat(Arrays.stream(Checkpointer.class.getMethods())
                .filter(method -> Set.of("save", "load", "delete").contains(method.getName()))
                .filter(method -> method.getParameterTypes()[0] != TenantContext.class))
                .isEmpty();
    }

    private ChatSessionMapper chatSessionMapper;
    private MySqlCheckpointer checkpointer;

    @BeforeEach
    void setUp() {
        chatSessionMapper = Mockito.mock(ChatSessionMapper.class);
        checkpointer = new MySqlCheckpointer(chatSessionMapper, new ObjectMapper());
    }

    @Test
    void shouldSaveStateWithCheckpointMetadata() {
        TenantContext tenant = new TenantContext(1L, "admin");
        AgentState state = AgentState.create("sess_1", "查看质检队列", "admin")
                .set(AgentState.KEY_TENANT_USER_ID, 1L)
                .set(AgentState.KEY_CURRENT_NODE, "detection_agent")
                .set(AgentState.KEY_EXIT_REASON, AgentState.EXIT_COMPLETE);
        when(chatSessionMapper.updateCheckpointForTenant(
                eq(1L), eq("sess_1"), Mockito.anyString(), eq("detection_agent"), eq("COMPLETE")))
                .thenReturn(1);

        checkpointer.save(tenant, "sess_1", state);

        ArgumentCaptor<String> jsonCaptor = ArgumentCaptor.forClass(String.class);
        verify(chatSessionMapper).updateCheckpointForTenant(
                eq(1L),
                eq("sess_1"),
                jsonCaptor.capture(),
                eq("detection_agent"),
                eq("COMPLETE")
        );
        assertThat(jsonCaptor.getValue()).contains("\"thread_id\":\"sess_1\"");
        assertThat(jsonCaptor.getValue()).contains("\"current_node\":\"detection_agent\"");
    }

    @Test
    void shouldLoadStateFromJson() {
        TenantContext tenant = new TenantContext(1L, "admin");
        when(chatSessionMapper.selectStateJsonForTenant(1L, "sess_1"))
                .thenReturn("{\"thread_id\":\"sess_1\",\"current_node\":\"human_confirm\",\"iteration\":2}");

        AgentState state = checkpointer.load(tenant, "sess_1");

        assertThat(state.getString(AgentState.KEY_THREAD_ID)).isEqualTo("sess_1");
        assertThat(state.getString(AgentState.KEY_CURRENT_NODE)).isEqualTo("human_confirm");
        assertThat(state.getInt(AgentState.KEY_ITERATION)).isEqualTo(2);
    }

    @Test
    void shouldClearCheckpointWhenDeleted() {
        TenantContext tenant = new TenantContext(1L, "admin");
        checkpointer.delete(tenant, "sess_1");

        verify(chatSessionMapper).clearCheckpointForTenant(1L, "sess_1");
    }

    @Test
    void shouldSaveCheckpointWithTenantUserId() {
        TenantContext tenant = new TenantContext(42L, "alice");
        AgentState state = AgentState.create("sess_1", "hello", "alice")
                .set(AgentState.KEY_TENANT_USER_ID, 42L);
        when(chatSessionMapper.updateCheckpointForTenant(
                eq(42L), eq("sess_1"), Mockito.anyString(), Mockito.isNull(), Mockito.isNull()))
                .thenReturn(1);

        checkpointer.save(tenant, "sess_1", state);

        verify(chatSessionMapper).updateCheckpointForTenant(
                eq(42L), eq("sess_1"), Mockito.anyString(), Mockito.isNull(), Mockito.isNull());
    }
}
