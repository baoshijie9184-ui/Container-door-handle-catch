package com.ruanzhu.doorhandle.module.ai.workbench;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.time.LegacyClockEvidence;
import com.ruanzhu.doorhandle.framework.persistence.workflow.LegacyWorkflowClocks;
import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowKind;
import java.math.BigInteger;
import java.util.*;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

/** Pure protocol cases still execute only in the admitted ECS verification reactor. */
class LegacyClockProtocolTest {
    private final ObjectMapper json=new ObjectMapper();
    private String clock(String table,Map<String,?> key,Map<String,String> wall)throws Exception{
        var body=new LinkedHashMap<String,Object>();body.put("protocol",LegacyClockEvidence.PROTOCOL);body.put("status","UNRESOLVED");
        body.put("sourceTable",table);body.put("sourceKey",key);body.put("sourceSnapshotSha256","a".repeat(64));body.put("sourceRowSha256","b".repeat(64));body.put("sourceWallTimes",wall);
        return json.writeValueAsString(body);
    }
    @Test void unknownWorkbenchRequiresSidecarAndRetainsExactWallStrings()throws Exception{
        var protocol=new WorkbenchProtocol(json);var wall=Map.of("created_at","2025-03-04 12:13:14.123456","updated_at","2026-01-02 03:04:05.654321");
        var payload=protocol.payload("TOOL_TIMING",Map.of("durationMs",12L),new WorkbenchProtocol.LegacyItemV1("{ \"durationMs\" : 12 }",wall.get("created_at"),wall.get("updated_at"),null),true);
        String encoded=protocol.write(payload);var evidence=LegacyClockEvidence.parse(clock("agent_workbench_item",Map.of("id",new BigInteger("9223372036854775810")),wall),"agent_workbench_item",Map.of("id",new BigInteger("9223372036854775810")));
        assertThatThrownBy(()->protocol.read("TOOL_TIMING",1,encoded)).isInstanceOf(IllegalStateException.class);
        var read=protocol.read("TOOL_TIMING",1,encoded,evidence);
        assertThat(read.schemaVersion()).isEqualTo(2);assertThat(read.legacy().sourceUtcOffset()).isNull();assertThat(read.legacy().payloadJson()).isEqualTo(payload.legacy().payloadJson());
        assertThat(((Number)protocol.data(read).get("durationMs")).longValue()).isEqualTo(12L);
    }
    @Test void fixedOffsetVersionOneCannotBeRelabelledUnresolved()throws Exception{
        var protocol=new WorkbenchProtocol(json);var wall=Map.of("created_at","2025-01-02 00:00:00","updated_at","2025-01-02 00:00:01");
        var payload=protocol.payload("TOOL_TIMING",Map.of("durationMs",3L),new WorkbenchProtocol.LegacyItemV1("{}",wall.get("created_at"),wall.get("updated_at"),"+08:00"));
        assertThat(protocol.read("TOOL_TIMING",1,protocol.write(payload)).schemaVersion()).isEqualTo(1);
        var evidence=LegacyClockEvidence.parse(clock("agent_workbench_item",Map.of("id",1),wall),"agent_workbench_item",Map.of("id",1));
        assertThatThrownBy(()->protocol.read("TOOL_TIMING",1,protocol.write(payload),evidence)).isInstanceOf(IllegalStateException.class);
    }
    @Test void changedWorkbenchWallValueDoesNotPassCivilProvenance()throws Exception{
        var protocol=new WorkbenchProtocol(json);var wall=Map.of("created_at","2025-01-02 00:00:00","updated_at","2025-01-02 00:00:01");
        var payload=protocol.payload("TOOL_TIMING",Map.of("durationMs",3L),new WorkbenchProtocol.LegacyItemV1("{}","2025-01-02 08:00:00",wall.get("updated_at"),null),true);
        var evidence=LegacyClockEvidence.parse(clock("agent_workbench_item",Map.of("id",1),wall),"agent_workbench_item",Map.of("id",1));
        assertThatThrownBy(()->protocol.read("TOOL_TIMING",1,protocol.write(payload),evidence)).isInstanceOf(IllegalStateException.class);
    }
    @Test void reportAndApprovalSourcesKeepTheirActualStringAndCompositePrimaryKeys()throws Exception{
        var empty=Map.<String,String>of();
        var catalog=json.readTree(java.nio.file.Files.readString(java.nio.file.Path.of("../docs/database/legacy-clock-source-catalog.json"))).path("tables");
        for(var entry:Map.of("detection_report_outbox",List.of("event_id"),"detection_report_event_receipt",List.of("event_id"),"detection_report_confirmation",List.of("token"),"agent_pending_action",List.of("action_id"),"detection_report_command",List.of("actor_user_id","request_id"),"detection_report_agent_origin",List.of("actor_user_id","request_id")).entrySet())
            assertThat(catalog.path(entry.getKey()).path("primaryKey")).isEqualTo(json.valueToTree(entry.getValue()));
        assertThat(LegacyWorkflowClocks.read(clock("detection_report_outbox",Map.of("event_id","event-a"),empty),WorkflowKind.REPORT_DELIVERY,"detection_report_outbox","event-a").sourceKey()).containsEntry("event_id","event-a");
        assertThat(LegacyWorkflowClocks.read(clock("detection_report_confirmation",Map.of("token","confirmation-a"),empty),WorkflowKind.REPORT_CONFIRMATION,"detection_report_confirmation","confirmation-a").sourceKey()).containsEntry("token","confirmation-a");
        assertThat(LegacyWorkflowClocks.read(clock("agent_pending_action",Map.of("action_id","action-a"),empty),WorkflowKind.AGENT_ACTION,"agent_pending_action","action-a").sourceKey()).containsEntry("action_id","action-a");
        var composite=clock("detection_report_command",Map.of("actor_user_id",7,"request_id","req-a"),empty);
        assertThat(LegacyWorkflowClocks.read(composite,WorkflowKind.REPORT_COMMAND,"detection_report_command","[7, \"req-a\"]").sourceKey()).containsEntry("actor_user_id",BigInteger.valueOf(7));
        assertThatThrownBy(()->LegacyWorkflowClocks.read(composite,WorkflowKind.REPORT_COMMAND,"detection_report_command","[8, \"req-a\"]")).isInstanceOf(IllegalStateException.class);
    }
    @Test void logicalTaskSidecarNamesItsRealSourceInsteadOfSyntheticTargetAlias()throws Exception{
        String evidence=clock("agent_workbench_item",Map.of("id",3),Map.of("updated_at","2025-01-02 00:00:00"));
        assertThat(LegacyWorkflowClocks.read(evidence,WorkflowKind.WORKBENCH_LOGICAL_TASK,"agent_workbench_logical_task","3").sourceTable()).isEqualTo("agent_workbench_item");
        assertThatThrownBy(()->LegacyWorkflowClocks.read(evidence,WorkflowKind.MCP_INSTALL_JOB,"agent_mcp_install_job","3")).isInstanceOf(IllegalStateException.class);
    }
    @Test void everyNumericWorkflowSourceUsesTheReviewedCatalogPrimaryKey()throws Exception{
        var catalog=json.readTree(java.nio.file.Files.readString(java.nio.file.Path.of("../docs/database/legacy-clock-source-catalog.json"))).path("tables");
        var sources=Map.ofEntries(Map.entry(WorkflowKind.CONVERSATION_INPUT,"agent_conversation_input"),
            Map.entry(WorkflowKind.SKILL_IMPORT_COMMAND,"agent_skill_import"),Map.entry(WorkflowKind.SKILL_DOWNLOAD,"agent_skill_download"),Map.entry(WorkflowKind.SKILL_STORAGE_COMMAND,"agent_skill_storage_command"),
            Map.entry(WorkflowKind.MEMORY_MUTATION,"agent_memory_audit"),Map.entry(WorkflowKind.WORKSPACE_MUTATION,"agent_workspace_request"),Map.entry(WorkflowKind.WORKSPACE_FORK,"agent_session_fork"),Map.entry(WorkflowKind.LEGACY_CHAT_ACTION,"chat_pending_action"),
            Map.entry(WorkflowKind.MCP_INSTALL_JOB,"agent_mcp_install_job"),Map.entry(WorkflowKind.MCP_EXECUTION,"agent_mcp_execution"),Map.entry(WorkflowKind.MCP_EXECUTION_COMMAND,"agent_mcp_execution_command"),Map.entry(WorkflowKind.MCP_INSTALLATION,"agent_fetch_installation"),Map.entry(WorkflowKind.MCP_LIFECYCLE_COMMAND,"agent_fetch_lifecycle_command"),Map.entry(WorkflowKind.MCP_INSTALL_WORKER,"agent_mcp_install_worker"),Map.entry(WorkflowKind.MCP_IMAGE_COMMAND,"agent_fetch_image_command"),Map.entry(WorkflowKind.WORKBENCH_COMMAND,"agent_workbench_request"));
        for(var entry:sources.entrySet()){
            assertThat(catalog.path(entry.getValue()).path("primaryKey")).isEqualTo(json.readTree("[\"id\"]"));
            var proof=clock(entry.getValue(),Map.of("id",17),Map.of());
            assertThat(LegacyWorkflowClocks.read(proof,entry.getKey(),entry.getValue(),"17").sourceKey()).containsEntry("id",BigInteger.valueOf(17));
        }
        for(var kind:WorkflowKind.values())if(kind.name().startsWith("WORKBENCH_")&&kind!=WorkflowKind.WORKBENCH_COMMAND){
            String stored=kind==WorkflowKind.WORKBENCH_LOGICAL_TASK?"agent_workbench_logical_task":"agent_workbench_item";
            assertThat(LegacyWorkflowClocks.read(clock("agent_workbench_item",Map.of("id",17),Map.of()),kind,stored,"17").sourceTable()).isEqualTo("agent_workbench_item");
        }
        assertThatThrownBy(()->LegacyWorkflowClocks.read(clock("agent_skill_import_request",Map.of("id",17),Map.of()),WorkflowKind.SKILL_IMPORT_COMMAND,"agent_skill_import_request","17")).isInstanceOf(IllegalStateException.class);
    }
}
