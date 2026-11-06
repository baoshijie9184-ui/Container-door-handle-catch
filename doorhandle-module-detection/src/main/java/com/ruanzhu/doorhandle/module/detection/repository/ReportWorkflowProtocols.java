package com.ruanzhu.doorhandle.module.detection.repository;

import com.ruanzhu.doorhandle.framework.persistence.workflow.*;
import java.util.Map;
import java.util.Set;

/** Report-owned, versioned protocols; shared storage does not interpret report payloads. */
public final class ReportWorkflowProtocols {
    private ReportWorkflowProtocols() { }
    public record CommandV1(String responseJson) { }
    public record ConfirmationV1(String snapshotSha256, String decisionSha256) { }
    public record DeliveryV1(String eventType, String eventJson) { }
    public record ConsumptionV1(String eventType, String payloadSha256) { }
    public record AgentOriginV1(String callId, String toolName) { }
    public record AuditV1(String actorUsername, String beforeStatus, String afterStatus, String reason) { }
    public record EventStateV1(String reportId, String lastEventId, int lastVersion, String status) { }

    public static WorkflowProtocols protocols() {
        return WorkflowProtocols.defaults()
                .with(new WorkflowProtocol<>(WorkflowKind.REPORT_COMMAND,1,CommandV1.class,Set.of("COMPLETED"),Set.of("COMPLETED"),Map.of(),p->text(p.responseJson(),2_000_000)))
                .with(new WorkflowProtocol<>(WorkflowKind.REPORT_AGENT_ORIGIN,1,AgentOriginV1.class,Set.of("COMPLETED"),Set.of("COMPLETED"),Map.of(),p->{
                    text(p.callId(),160);if(!Set.of("create_report_draft","edit_report_draft").contains(p.toolName()))throw new IllegalArgumentException("Invalid report tool");
                }))
                .with(new WorkflowProtocol<>(WorkflowKind.REPORT_CONFIRMATION,1,ConfirmationV1.class,Set.of("PENDING"),Set.of("USED","EXPIRED"),Map.of("PENDING",Set.of("USED","EXPIRED")),p->{sha(p.snapshotSha256());sha(p.decisionSha256());}))
                .with(new WorkflowProtocol<>(WorkflowKind.REPORT_DELIVERY,1,DeliveryV1.class,Set.of("PENDING"),Set.of("DELIVERED"),Map.of(
                        "PENDING",Set.of("PROCESSING","RETRY"),"RETRY",Set.of("PROCESSING","RETRY"),
                        "PROCESSING",Set.of("PROCESSING","RETRY","FAILED","DELIVERED"),"FAILED",Set.of("RETRY")),p->{text(p.eventType(),80);text(p.eventJson(),65_535);},true))
                .with(new WorkflowProtocol<>(WorkflowKind.REPORT_CONSUMPTION,1,ConsumptionV1.class,Set.of("COMPLETED"),Set.of("COMPLETED"),Map.of(),p->{text(p.eventType(),80);sha(p.payloadSha256());}));
    }
    private static void text(String value,int length) { if(value==null||value.isBlank()||value.length()>length)throw new IllegalArgumentException("Invalid report workflow payload"); }
    private static void sha(String value) { if(value==null||!value.matches("[a-f0-9]{64}"))throw new IllegalArgumentException("Invalid report workflow digest"); }
}
