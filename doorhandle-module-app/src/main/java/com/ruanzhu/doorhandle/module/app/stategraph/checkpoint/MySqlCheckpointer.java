package com.ruanzhu.doorhandle.module.app.stategraph.checkpoint;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.app.mapper.ChatSessionMapper;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import com.ruanzhu.doorhandle.module.app.stategraph.core.AgentState;
import com.ruanzhu.doorhandle.module.app.stategraph.core.StateGraphException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 基于 MySQL chat_session.state_json 列的 Checkpointer 实现。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class MySqlCheckpointer implements Checkpointer {

    private final ChatSessionMapper chatSessionMapper;
    private final ObjectMapper objectMapper;

    @Override
    public void save(TenantContext tenant, String threadId, AgentState state) {
        try {
            String json = objectMapper.writeValueAsString(state.toMap());
            int updated = chatSessionMapper.updateCheckpointForTenant(
                    tenant.userId(), threadId, json,
                    state.getString(AgentState.KEY_CURRENT_NODE),
                    state.getString(AgentState.KEY_EXIT_REASON));
            if (updated == 0) {
                throw new StateGraphException("Checkpoint 会话不存在或不属于当前租户: thread_id=" + threadId);
            }
        } catch (JsonProcessingException e) {
            throw new StateGraphException("Checkpoint 序列化失败", e, state);
        }
    }

    @Override
    public AgentState load(TenantContext tenant, String threadId) {
        return deserialize(chatSessionMapper.selectStateJsonForTenant(tenant.userId(), threadId), threadId);
    }

    @Override
    public void delete(TenantContext tenant, String threadId) {
        chatSessionMapper.clearCheckpointForTenant(tenant.userId(), threadId);
    }

    private AgentState deserialize(String json, String threadId) {
        if (json == null || json.isEmpty()) return null;
        try {
            Map<String, Object> map = objectMapper.readValue(json, new TypeReference<Map<String, Object>>() {});
            return AgentState.fromMap(map);
        } catch (JsonProcessingException e) {
            throw new StateGraphException("Checkpoint 反序列化失败: thread_id=" + threadId, e);
        }
    }
}
