package com.ruanzhu.doorhandle.module.ai.context;

import java.util.Optional;

/** Current child identity only; immutable source snapshots remain owned by the context domain. */
public interface ChildProvenanceReader {
    Optional<ChildProvenance> find(long ownerUserId, String sessionId, String itemId);
    record ChildProvenance(String id, long ownerUserId, String sessionId, String status, long revision) {}
}
