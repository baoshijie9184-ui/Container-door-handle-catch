package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.agent.OperationsAuditApi;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Component;

@Component
public class DetectionWorkUnitAudit {
    private final ObjectProvider<OperationsAuditApi> audit;

    public DetectionWorkUnitAudit(ObjectProvider<OperationsAuditApi> audit) {
        this.audit = audit;
    }

    public void record(Identity identity, String action, String resourceId, String requestId, long version) {
        audit.ifAvailable(sink -> {
            var role = identity.supervisor() ? AgentActor.Role.SUPERVISOR : AgentActor.Role.INSPECTOR;
            var actor = new AgentActor(identity.userId(), identity.username(), role);
            sink.append(new OperationsAuditApi.Event(actor, "ENTERPRISE", "DETECTION", action,
                    resourceId, requestId, "APPLIED", version));
        });
    }
}
