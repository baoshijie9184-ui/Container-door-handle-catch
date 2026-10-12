package com.ruanzhu.doorhandle.contracts.agent;

import java.util.List;

public interface ModelAgentReadApi {
    record ModelView(Integer modelId, String name, String version, String status, Boolean defaultModel) {}
    List<ModelView> models(AgentActor actor, int page, int size);
}
