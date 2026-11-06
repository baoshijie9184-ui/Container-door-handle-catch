package com.ruanzhu.doorhandle.framework.persistence.workflow;

import java.util.Map;
import java.util.Set;
import java.util.function.Consumer;

/** A protocol owns its state machine and typed versioned payload. */
public record WorkflowProtocol<P>(WorkflowKind kind, int payloadVersion, Class<P> payloadType,
        Set<String> initialStates, Set<String> terminalStates, Map<String, Set<String>> transitions,
        Consumer<P> validator, boolean reclaimable) {
    public WorkflowProtocol(WorkflowKind kind, int payloadVersion, Class<P> payloadType,
            Set<String> initialStates, Set<String> terminalStates, Map<String, Set<String>> transitions,
            Consumer<P> validator) {
        this(kind, payloadVersion, payloadType, initialStates, terminalStates, transitions, validator, false);
    }
    public WorkflowProtocol {
        if (kind == null || payloadVersion < 1 || payloadType == null || validator == null)
            throw new IllegalArgumentException("Incomplete workflow protocol");
        initialStates = Set.copyOf(initialStates); terminalStates = Set.copyOf(terminalStates);
        transitions = transitions.entrySet().stream().collect(java.util.stream.Collectors.toUnmodifiableMap(
                Map.Entry::getKey, e -> Set.copyOf(e.getValue())));
    }
    public void validatePayload(Object payload, int version) {
        if (version != payloadVersion || !payloadType.isInstance(payload))
            throw new IllegalArgumentException("Unsupported payload type/version for " + kind);
        validator.accept(payloadType.cast(payload));
    }
    public void requireInitial(String state) {
        if (!initialStates.contains(state)) throw new IllegalArgumentException("Invalid initial state for " + kind);
    }
    public void requireTransition(String before, String after) {
        if (terminalStates.contains(before) || !transitions.getOrDefault(before, Set.of()).contains(after))
            throw new WorkflowConflictException("State transition rejected for " + kind + ": " + before + " -> " + after);
    }
}
