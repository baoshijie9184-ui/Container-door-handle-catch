package com.ruanzhu.doorhandle.module.ai.mcp;

import com.ruanzhu.doorhandle.common.time.LegacyClockEvidence;
import com.ruanzhu.doorhandle.framework.persistence.workflow.LegacyWorkflowClocks;
import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowKind;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

/** Validates old clock provenance without interpreting a missing lease as an exit. */
final class LegacyMcpClocks {
    private LegacyMcpClocks() {}
    static LegacyClockEvidence connector(Map<String,Object> row){
        if(!row.containsKey("legacy_clock_json"))throw new IllegalStateException("MCP clock evidence column is missing");
        Object raw=row.get("legacy_clock_json");
        var clock=raw==null?null:LegacyClockEvidence.parse(raw.toString(),"agent_local_mcp",Map.of("id",((Number)row.get("id")).longValue()));
        absoluteTimes(row,clock);return clock;
    }
    static LegacyClockEvidence workflow(Map<String,Object> row,WorkflowKind kind){
        if(!row.containsKey("legacy_clock_json"))throw new IllegalStateException("MCP clock evidence column is missing");
        Object raw=row.get("legacy_clock_json");
        var clock=LegacyWorkflowClocks.read(raw==null?null:raw.toString(),kind,(String)row.get("legacy_source"),(String)row.get("legacy_key"));
        absoluteTimes(row,clock);return clock;
    }
    static void requireResolved(LegacyClockEvidence clock){
        if(clock!=null)throw new ResponseStatusException(HttpStatus.CONFLICT,"历史 MCP 时钟待核对，不能自动执行、释放或清理");
    }
    static LegacyClockEvidence audit(Map<String,Object> row){
        if(!row.containsKey("legacy_clock_json"))throw new IllegalStateException("MCP clock evidence column is missing");
        Object raw=row.get("legacy_clock_json");if(raw==null)return null;
        String source=(String)row.get("legacy_source"),key=(String)row.get("legacy_key");
        if(!java.util.Set.of("agent_local_mcp_audit","agent_fetch_image_retention_event").contains(source)||key==null||!key.matches("[1-9][0-9]*"))throw new IllegalStateException("MCP audit original identity differs");
        var clock=LegacyClockEvidence.parse(raw.toString(),source,Map.of("id",new java.math.BigInteger(key)));absoluteTimes(row,clock);return clock;
    }
    private static void absoluteTimes(Map<String,Object> row,LegacyClockEvidence clock){
        if(clock!=null)for(String column:java.util.List.of("created_at","updated_at","lease_expires_at","createdAt","updatedAt"))
            if(row.get(column)!=null)throw new IllegalStateException("Unresolved MCP evidence cannot invent an absolute time");
    }
    static void display(Map<String,Object> row,LegacyClockEvidence clock){
        row.remove("legacy_clock_json");row.remove("legacy_source");row.remove("legacy_key");
        if(clock!=null){row.put("clockStatus",clock.clockStatus());row.put("sourceWallTimes",clock.sourceWallTimes());}
    }
}
