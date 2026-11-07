package com.ruanzhu.doorhandle.framework.persistence.workflow;

import com.ruanzhu.doorhandle.common.time.LegacyClockEvidence;
import java.math.BigInteger;
import java.util.Map;
import java.util.Set;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.DeserializationFeature;

/** Binds retained wall-clock provenance to the closed operation kind and original PK. */
public final class LegacyWorkflowClocks {
    private static final ObjectMapper JSON=new ObjectMapper().enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);
    // Closed source PK catalog: reviewed against legacy-clock-source-catalog.json
    // and every workflow INSERT in the thirteen unresolved-domain copy scripts.
    private static final Set<String> NUMERIC_ID_SOURCES=Set.of("agent_conversation_input","agent_skill_download",
            "agent_skill_storage_command","agent_skill_import","agent_session_fork","agent_workspace_request",
            "agent_memory_audit","chat_pending_action","agent_workbench_item","agent_workbench_request",
            "agent_mcp_install_job","agent_mcp_execution","agent_mcp_execution_command","agent_fetch_installation",
            "agent_fetch_lifecycle_command","agent_mcp_install_worker","agent_fetch_image_command");
    private LegacyWorkflowClocks() {}
    public static LegacyClockEvidence read(String raw, WorkflowKind kind, String legacySource, String legacyKey) {
        if (raw == null) return null;
        String expected = switch (kind) {
            case CONVERSATION_INPUT -> "agent_conversation_input";
            case SKILL_DOWNLOAD -> "agent_skill_download";
            case SKILL_STORAGE_COMMAND -> "agent_skill_storage_command";
            case SKILL_IMPORT_COMMAND -> "agent_skill_import";
            case WORKSPACE_FORK -> "agent_session_fork";
            case WORKSPACE_MUTATION -> "agent_workspace_request";
            case MEMORY_MUTATION -> "agent_memory_audit";
            case AGENT_ACTION -> "agent_pending_action";
            case LEGACY_CHAT_ACTION -> "chat_pending_action";
            case REPORT_DELIVERY -> "detection_report_outbox";
            case REPORT_CONSUMPTION -> "detection_report_event_receipt";
            case REPORT_CONFIRMATION -> "detection_report_confirmation";
            case REPORT_COMMAND -> "detection_report_command";
            case REPORT_AGENT_ORIGIN -> "detection_report_agent_origin";
            case WORKBENCH_COMMAND -> "agent_workbench_request";
            case MCP_INSTALL_JOB -> "agent_mcp_install_job";
            case MCP_EXECUTION -> "agent_mcp_execution";
            case MCP_EXECUTION_COMMAND -> "agent_mcp_execution_command";
            case MCP_INSTALLATION -> "agent_fetch_installation";
            case MCP_LIFECYCLE_COMMAND -> "agent_fetch_lifecycle_command";
            case MCP_INSTALL_WORKER -> "agent_mcp_install_worker";
            case MCP_IMAGE_COMMAND -> "agent_fetch_image_command";
            default -> {if(kind.name().startsWith("WORKBENCH_"))yield "agent_workbench_item";
                throw new IllegalStateException("No registered legacy clock source for this workflow kind");}
        };
        String storedSource = kind == WorkflowKind.WORKBENCH_LOGICAL_TASK ? "agent_workbench_logical_task" : expected;
        if (expected == null || !storedSource.equals(legacySource) || legacyKey == null)
            throw new IllegalStateException("Legacy clock operation identity differs");
        Map<String,?> key=switch(kind){
            case REPORT_DELIVERY,REPORT_CONSUMPTION -> Map.of("event_id",legacyKey);
            case REPORT_CONFIRMATION -> Map.of("token",legacyKey);
            case AGENT_ACTION -> Map.of("action_id",legacyKey);
            case REPORT_COMMAND,REPORT_AGENT_ORIGIN -> actorRequest(legacyKey);
            default -> {if(!NUMERIC_ID_SOURCES.contains(expected))throw new IllegalStateException("No registered legacy clock primary key");yield numericId(legacyKey);}
        };
        return LegacyClockEvidence.parse(raw, expected, key);
    }
    private static Map<String,?> numericId(String key){
        if(!key.matches("(?:0|-?[1-9][0-9]*)"))throw new IllegalStateException("Legacy source primary key differs");
        return Map.of("id",new BigInteger(key));
    }
    private static Map<String,?> actorRequest(String key){
        try{
            var node=JSON.readTree(key);
            if(!node.isArray()||node.size()!=2||!node.get(0).isIntegralNumber()||node.get(0).bigIntegerValue().signum()<=0||!node.get(1).isTextual()||node.get(1).textValue().isBlank())throw new IllegalStateException();
            return Map.of("actor_user_id",node.get(0).bigIntegerValue(),"request_id",node.get(1).textValue());
        }catch(Exception error){throw new IllegalStateException("Legacy source composite primary key differs");}
    }
    public static void requireResolved(WorkflowRecord record) {
        if (record.legacyClockUnresolved())
            throw new WorkflowConflictException("历史时钟待核对，不能自动执行或改变租约");
    }
}
