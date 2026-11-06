package com.ruanzhu.doorhandle.module.ai.model;

import com.ruanzhu.doorhandle.framework.persistence.workflow.*;
import java.util.Map;
import java.util.Set;

/** A token grant request is permanent; it neither enables a model nor allocates enterprise tokens. */
final class PersonalModelQuotaWorkflow {
    private PersonalModelQuotaWorkflow() { }
    record ApplicationV1(String reason) {
        ApplicationV1 { reason(reason); }
        private static void reason(String value) {
            if(value==null||value.isBlank()||value.length()>500)throw new IllegalArgumentException("Invalid quota request reason");
        }
    }
    record DecisionV1(String decision,long actorUserId,String requestId,String requestSha256,String reason,
                      long expectedVersion,Long totalBefore,Long totalAfter) { }
    record AuditV1(String modelId,long requestedTokens,String reason) { }
    record ApplicationDigest(String action,String modelId,long requestedTokens,String reason) { }
    record DecisionDigest(String action,String applicationId,long expectedVersion,String reason) { }
    static WorkflowProtocol<ApplicationV1> protocol() {
        return new WorkflowProtocol<>(WorkflowKind.LLM_QUOTA_APPLICATION,1,ApplicationV1.class,
                Set.of("PENDING"),Set.of("APPROVED","REJECTED","CANCELLED"),
                Map.of("PENDING",Set.of("APPROVED","REJECTED","CANCELLED")),value->{},false);
    }
}
