package com.ruanzhu.doorhandle.module.ai.mcp;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowKind;
import java.util.*;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class LegacyMcpClockTest {
    private Map<String,Object> row(String table)throws Exception{
        String proof=new ObjectMapper().writeValueAsString(Map.of("protocol","doorhandle-legacy-clock-v1","status","UNRESOLVED","sourceTable",table,"sourceKey",Map.of("id",17),"sourceSnapshotSha256","a".repeat(64),"sourceRowSha256","b".repeat(64),"sourceWallTimes",Map.of("created_at","2020-01-02 00:00:00")));
        var row=new LinkedHashMap<String,Object>();row.put("id",17L);row.put("legacy_source",table);row.put("legacy_key","17");row.put("legacy_clock_json",proof);row.put("status","RUNNING");row.put("reserved_bytes",2097152L);return row;
    }
    @Test void unresolvedInstallerNeverBecomesAnExitOrCapacityRelease()throws Exception{
        var row=row("agent_mcp_install_worker");var clock=LegacyMcpClocks.workflow(row,WorkflowKind.MCP_INSTALL_WORKER);
        assertThatThrownBy(()->LegacyMcpClocks.requireResolved(clock)).hasMessageContaining("历史");
        assertThat(row).containsEntry("status","RUNNING").containsEntry("reserved_bytes",2097152L);
        LegacyMcpClocks.display(row,clock);assertThat(row).containsEntry("clockStatus","UNRESOLVED").doesNotContainKeys("legacy_clock_json","legacy_source","legacy_key");
    }
    @Test void mismatchedKindCannotReuseAnotherOriginalClockProof()throws Exception{
        var row=row("agent_mcp_install_worker");
        assertThatThrownBy(()->LegacyMcpClocks.workflow(row,WorkflowKind.MCP_EXECUTION)).isInstanceOf(IllegalStateException.class);
    }
    @Test void missingClockColumnIsNotAResolvedClockFallback(){
        assertThatThrownBy(()->LegacyMcpClocks.connector(new LinkedHashMap<>(Map.of("id",17L)))).isInstanceOf(IllegalStateException.class);
        var current=new LinkedHashMap<String,Object>();current.put("id",17L);current.put("legacy_clock_json",null);
        assertThat(LegacyMcpClocks.connector(current)).isNull();
    }
}
