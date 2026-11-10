package com.ruanzhu.doorhandle.contracts.collaboration;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

/** Domain-owned allowlist and locked persisted values; never a generic entity serializer. */
public interface BusinessMutationParticipant {
    record Snapshot(String resourceType, String resourceId, Long version, Map<String,Object> fields,
                    Set<String> maskedFields, Set<String> secretFields) {
        public Snapshot {
            fields = Collections.unmodifiableMap(new LinkedHashMap<>(fields));
            maskedFields = Set.copyOf(maskedFields); secretFields = Set.copyOf(secretFields);
        }
    }
    boolean supports(String domain, String action);
    /** Resolve identifiers from fixed server method arguments; result is null before execution. */
    String resourceId(String domain, String action, Object[] arguments, Object result);
    /** Before uses SELECT FOR UPDATE; after re-reads actual committed-in-this-transaction values. */
    Snapshot capture(AgentActor actor, String domain, String action, String resourceId, boolean lock);
    /** Canonicalizable input for SHA-256 only, never persisted as audit history or raw command payload. */
    Object digestInput(String action, Object[] arguments);
    /** Creation has no expected existing version. All other user writes require it. */
    default boolean creates(String action) { return false; }
}
