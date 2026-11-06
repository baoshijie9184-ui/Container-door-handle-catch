package com.ruanzhu.doorhandle.framework.persistence.workflow;

import java.util.EnumMap;
import java.util.Map;
import java.util.Set;

/** Immutable registry; modules may add explicit protocols, never arbitrary SQL or state names. */
public final class WorkflowProtocols {
    private final Map<WorkflowKind, WorkflowProtocol<?>> protocols;
    private WorkflowProtocols(Map<WorkflowKind, WorkflowProtocol<?>> protocols) { this.protocols = Map.copyOf(protocols); }
    public static WorkflowProtocols defaults() {
        var values = new EnumMap<WorkflowKind, WorkflowProtocol<?>>(WorkflowKind.class);
        values.put(WorkflowKind.CONVERSATION_INPUT, new WorkflowProtocol<>(WorkflowKind.CONVERSATION_INPUT, 1,
                WorkflowPayloads.ConversationInputV1.class, Set.of("QUEUED"),
                Set.of("APPLIED", "COMPLETED", "CANCELLED", "FAILED", "EXPIRED"),
                Map.of("QUEUED", Set.of("QUEUED", "STARTED", "APPLIED", "CANCELLED", "FAILED", "EXPIRED"),
                        "STARTED", Set.of("COMPLETED", "FAILED", "EXPIRED")), value -> { }));
        values.put(WorkflowKind.KNOWLEDGE_COMMAND, receipt(WorkflowKind.KNOWLEDGE_COMMAND, WorkflowPayloads.KnowledgeCommandV1.class));
        values.put(WorkflowKind.WORKSPACE_FORK, receipt(WorkflowKind.WORKSPACE_FORK, WorkflowPayloads.WorkspaceForkV1.class));
        return new WorkflowProtocols(values);
    }
    private static <P> WorkflowProtocol<P> receipt(WorkflowKind kind, Class<P> type) {
        return new WorkflowProtocol<>(kind, 1, type, Set.of("COMPLETED"), Set.of("COMPLETED"), Map.of(), value -> { });
    }
    public WorkflowProtocols with(WorkflowProtocol<?> protocol) {
        var values = new EnumMap<WorkflowKind, WorkflowProtocol<?>>(WorkflowKind.class);
        values.putAll(protocols);
        if (values.putIfAbsent(protocol.kind(), protocol) != null)
            throw new IllegalArgumentException("Workflow kind already registered: " + protocol.kind());
        return new WorkflowProtocols(values);
    }
    public WorkflowProtocol<?> require(WorkflowKind kind) {
        var value = protocols.get(kind);
        if (value == null) throw new IllegalArgumentException("Unregistered workflow protocol: " + kind);
        return value;
    }
}
