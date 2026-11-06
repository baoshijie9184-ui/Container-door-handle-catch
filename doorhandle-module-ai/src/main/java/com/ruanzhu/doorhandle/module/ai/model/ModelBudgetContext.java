package com.ruanzhu.doorhandle.module.ai.model;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import java.util.Objects;

/** Server-owned reactive identity. Never populated from a model argument or request body. */
public record ModelBudgetContext(AgentActor actor, String runId) {
    public static final Object CONTEXT_KEY = ModelBudgetContext.class;
    public ModelBudgetContext {
        Objects.requireNonNull(actor, "Model accounting requires the authenticated actor");
        if (runId == null || runId.isBlank() || runId.length() > 128)
            throw new IllegalArgumentException("Missing model run identity");
    }
}
