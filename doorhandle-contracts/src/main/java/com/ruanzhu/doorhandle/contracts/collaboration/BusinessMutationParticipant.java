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
    /** Domains without an ORM version atomically advance their real row revision under the existing lock. */
    default Snapshot advanceVersion(Snapshot before, Snapshot after) { return after; }
    /** Acquire domain participant locks in a stable order before the common actor lock. */
    default void prepare(AgentActor actor,String domain,String action,String resourceId,Object[] arguments) { }
    /** Secondary resources retain their own domain when a command spans domain boundaries. */
    default String resourceDomain(Snapshot snapshot,String commandDomain) { return commandDomain; }
    /** Explicit secondary resources of a compound command (e.g. a device and its usage rows). */
    default java.util.List<Snapshot> related(AgentActor actor,String domain,String action,String resourceId,
            Object[] arguments,java.util.List<Snapshot> previous,boolean lock) { return java.util.List.of(); }
}
