package com.ruanzhu.doorhandle.module.ai.model;

import com.ruanzhu.doorhandle.framework.persistence.workflow.*;
import java.time.LocalDateTime;
import java.util.Map;
import java.util.Set;

/** Durable admission and completion receipts contain metadata, never prompts or credentials. */
final class ModelBudgetWorkflow {
    private ModelBudgetWorkflow() { }
    record RequestV1(String runId) { }
    record AttemptV1(String modelId, long reservedTokens, String reservationBasis) { }
    record ChangeV1(Long totalTokens, int warningPercent, LocalDateTime expiresAt) { }
    record ObservationV1(String sourceNote) { }
    record ReportV1(String status, Long inputTokens, Long outputTokens, Long cachedTokens) { }

    static WorkflowProtocols protocols() {
        return WorkflowProtocols.defaults()
                .with(new WorkflowProtocol<>(WorkflowKind.LLM_REQUEST, 1, RequestV1.class,
                        Set.of("OPEN"), Set.of("COMPLETED", "CANCELLED"),
                        Map.of("OPEN", Set.of("SETTLING", "NEEDS_REVIEW", "COMPLETED", "CANCELLED"),
                                "SETTLING", Set.of("NEEDS_REVIEW", "COMPLETED"),
                                "NEEDS_REVIEW", Set.of("NEEDS_REVIEW", "COMPLETED")),
                        value -> text(value.runId(), 128)))
                .with(new WorkflowProtocol<>(WorkflowKind.LLM_PROVIDER_ATTEMPT, 1, AttemptV1.class,
                        Set.of("RESERVED"), Set.of("COMPLETED", "FAILED", "CANCELLED"),
                        Map.of("RESERVED", Set.of("STARTED", "CANCELLED"),
                                "STARTED", Set.of("COMPLETED", "NEEDS_REVIEW"),
                                "NEEDS_REVIEW", Set.of("COMPLETED", "FAILED", "CANCELLED")), value -> {
                            model(value.modelId()); text(value.reservationBasis(), 64);
                            if (value.reservedTokens() <= 0) throw new IllegalArgumentException("Invalid token reservation");
                        }))
                .with(new WorkflowProtocol<>(WorkflowKind.LLM_QUOTA_CHANGE, 1, ChangeV1.class,
                        Set.of("COMPLETED"), Set.of("COMPLETED"), Map.of(), value -> {
                            if (value.totalTokens() != null && value.totalTokens() < 0
                                    || value.warningPercent() < 1 || value.warningPercent() > 100)
                                throw new IllegalArgumentException("Invalid quota policy");
                        }));
    }
    static void model(String id) {
        // openai-official is the actual ID produced by AgentModelService; openai is retained for old registrations.
        if (id == null || !id.matches("(dashscope|deepseek|openai|openai-official):[A-Za-z0-9._/-]{1,140}"))
            throw new IllegalArgumentException("Invalid model quota identity");
    }
    private static void text(String value, int limit) {
        if (value == null || value.isBlank() || value.length() > limit)
            throw new IllegalArgumentException("Invalid model workflow metadata");
    }
}
