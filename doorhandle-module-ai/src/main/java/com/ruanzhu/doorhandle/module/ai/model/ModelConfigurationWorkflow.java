package com.ruanzhu.doorhandle.module.ai.model;

import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowKind;
import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowProtocol;
import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowProtocols;
import java.util.Map;
import java.util.Set;

/** Model governance owns these protocols; a probe may have an unknown external outcome. */
final class ModelConfigurationWorkflow {
    private ModelConfigurationWorkflow() { }

    record CommandV1(String action, String target) { }
    record ProbeV1(String modelId) { }

    static WorkflowProtocols protocols() {
        return WorkflowProtocols.defaults()
                .with(new WorkflowProtocol<>(WorkflowKind.MODEL_CONFIG_COMMAND, 1, CommandV1.class,
                        Set.of("COMPLETED"), Set.of("COMPLETED"), Map.of(), value -> {
                            if (value.action() == null || !Set.of("VALIDATE", "PUBLISH", "REVOKE_KEY").contains(value.action()))
                                throw new IllegalArgumentException("Unknown model configuration action");
                            text(value.target(), 192);
                        }))
                .with(new WorkflowProtocol<>(WorkflowKind.MODEL_JSON_PROBE, 1, ProbeV1.class,
                        Set.of("STARTED"), Set.of("PASSED", "FAILED"),
                        Map.of("STARTED", Set.of("PASSED", "FAILED")), value -> text(value.modelId(), 160)));
    }

    private static void text(String value, int maximum) {
        if (value == null || value.isBlank() || value.length() > maximum)
            throw new IllegalArgumentException("Invalid model configuration workflow payload");
    }
}
