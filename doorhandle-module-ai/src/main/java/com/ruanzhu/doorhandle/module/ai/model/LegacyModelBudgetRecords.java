package com.ruanzhu.doorhandle.module.ai.model;

/** Immutable V64 source snapshots, not admission requests or reconstructed provider reservations. */
final class LegacyModelBudgetRecords {
    private LegacyModelBudgetRecords() { }
    record AttemptV1(String legacyId,String attemptId,String modelId,String status,Long inputTokens,Long outputTokens,
                     Long cachedTokens,String startedAtUtc,String finishedAtUtc) { }
    record AuditV1(String legacyId,String modelId,long actorUserId,String actionName,int version,String detailJson,String createdAtUtc) { }
}
