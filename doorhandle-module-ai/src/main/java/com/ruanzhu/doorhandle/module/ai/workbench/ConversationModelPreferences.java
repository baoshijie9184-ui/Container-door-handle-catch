package com.ruanzhu.doorhandle.module.ai.workbench;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.agent.AgentChatSessionApi;
import com.ruanzhu.doorhandle.module.ai.agent.AgentRunRegistry;
import com.ruanzhu.doorhandle.module.ai.model.AgentModelService;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

import static com.ruanzhu.doorhandle.module.ai.workbench.WorkbenchStore.fail;

@Service
@ConditionalOnExpression("${agentscope.ai.enabled:false} and ${agentscope.model-selection.enabled:false}")
public class ConversationModelPreferences {
    public record ModelSelection(String modelId, long revision) {}

    private final WorkbenchStore store;
    private final ObjectProvider<AgentChatSessionApi> sessions;
    private final AgentRunRegistry runs;
    private final AgentModelService models;

    public ConversationModelPreferences(WorkbenchStore store, ObjectProvider<AgentChatSessionApi> sessions,
                                        AgentRunRegistry runs, AgentModelService models) {
        this.store = store;
        this.sessions = sessions;
        this.runs = runs;
        this.models = models;
    }

    static ModelSelection read(WorkbenchStore store, AgentActor actor, String session) {
        var row = store.find(actor.userId(), session, WorkbenchStore.stable(actor.userId(), session, "model-selection"));
        return row == null ? new ModelSelection("", 0)
                : new ModelSelection(Objects.toString(row.data().get("modelId"), ""), row.revision());
    }

    public ModelSelection modelSelection(AgentActor actor, String session) {
        sessions.getObject().assertOwned(actor, session);
        return read(store, actor, session);
    }

    // The caller holds the process-wide run slot until the SDK has stopped.
    public AgentModelService.RunModel snapshot(AgentActor actor, String session) {
        sessions.getObject().assertOwned(actor, session);
        return store.locked(actor.userId(), () -> models.snapshot(read(store, actor, session).modelId()));
    }

    public ModelSelection selectModel(AgentActor actor, String session, String modelId, long revision,
                                      String request, Set<String> configured) {
        sessions.getObject().assertOwned(actor, session);
        return store.request(actor.userId(), request, store.encode(List.of(session, "select-model", modelId, revision)),
                ModelSelection.class, () -> {
                    if (!modelId.isEmpty() && !configured.contains(modelId)) throw fail(400, "模型未配置或不可选择");
                    var job = WorkbenchStore.mainSlot(store, actor.userId(), session).current();
                    if (runs.isActive(actor, session) || job != null && !Set.of("COMPLETED", "CANCELLED").contains(job.status()))
                        throw fail(409, "请先结束当前任务，再选择新任务使用的模型");
                    String id = WorkbenchStore.stable(actor.userId(), session, "model-selection");
                    var row = store.find(actor.userId(), session, id);
                    if (revision != (row == null ? 0 : row.revision())) throw fail(409, "模型选择已变化，请刷新核对");
                    if (row == null) row = store.create(actor.userId(), session, id, "MODEL_SELECTION", "ACTIVE", Map.of("modelId", ""));
                    var saved = store.update(row, "ACTIVE", Map.of("modelId", modelId), "MODEL_SELECTED");
                    return new ModelSelection(modelId, saved.revision());
                });
    }
}
