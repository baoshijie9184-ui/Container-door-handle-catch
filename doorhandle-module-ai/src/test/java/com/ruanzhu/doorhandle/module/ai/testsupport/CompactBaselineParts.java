package com.ruanzhu.doorhandle.module.ai.testsupport;

import java.util.List;
import java.util.Map;
import java.util.LinkedHashMap;
import java.nio.charset.StandardCharsets;
import org.springframework.core.io.ClassPathResource;
import org.springframework.core.io.support.EncodedResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.init.ScriptUtils;

/** The same complete source baseline used by the compact assembler, including provenance guards. */
public final class CompactBaselineParts {
    private CompactBaselineParts() {}
    public static List<String> all(){return List.of("10-core.sql","20-content.sql","25-agent.sql","30-operations.sql",
        "35-runtime-guards.sql","36-identity-guards.sql","37-audit-guards.sql","38-quota-guards.sql","39-workflow-guards.sql",
        "35-legacy-clock-content-asset.sql","35-legacy-clock-content-revision.sql","35-legacy-clock-content-link.sql",
        "35-legacy-clock-agent-run.sql","35-legacy-clock-agent-connector.sql","35-legacy-clock-runtime-state.sql",
        "35-legacy-clock-workflow-instance.sql","35-legacy-clock-audit-event.sql","35-legacy-clock-parent-model-management.sql",
        "35-legacy-clock-parent-chat-session.sql","35-legacy-clock-parent-users.sql",
        "35-legacy-clock-chat-projection.sql","40-relations.sql");}
    public static String separator(String name){return name.endsWith("-guards.sql")||name.startsWith("35-legacy-clock-")?"$$":";";}

    /** Install the complete MySQL guard set for the smaller classpath fixtures. */
    public static void installClockGuards(JdbcTemplate jdbc,String resource,String table)throws Exception{
        if(!Map.of("agent_run","db/compact/008-agent-run-clock-guards.sql",
                   "agent_connector","db/compact/009-agent-connector-clock-guards.sql").getOrDefault(table,"").equals(resource))
            throw new IllegalArgumentException("Unreviewed compact clock guard resource");
        try(var connection=jdbc.getDataSource().getConnection()){
            String product=connection.getMetaData().getDatabaseProductName();
            if("H2".equals(product))return;
            if(!"MySQL".equals(product))throw new IllegalStateException("MySQL clock guards require the admitted MySQL fixture");
        }
        String prefix="compact_legacy_clock_"+table;
        Map<String,String> expected=Map.of(prefix+"_update","BEFORE/UPDATE",prefix+"_delete","BEFORE/DELETE",
            prefix+"_binding_insert","AFTER/INSERT",prefix+"_binding_update","AFTER/UPDATE");
        var current=clockGuards(jdbc,table,expected);
        if(!current.isEmpty()){
            if(!current.equals(expected))throw new IllegalStateException("Partially installed or changed compact clock guard");
            return;
        }
        try(var connection=jdbc.getDataSource().getConnection()){
            ScriptUtils.executeSqlScript(connection,new EncodedResource(new ClassPathResource(resource),StandardCharsets.UTF_8),
                false,false,ScriptUtils.DEFAULT_COMMENT_PREFIX,"$$",ScriptUtils.DEFAULT_BLOCK_COMMENT_START_DELIMITER,
                ScriptUtils.DEFAULT_BLOCK_COMMENT_END_DELIMITER);
        }
        if(!clockGuards(jdbc,table,expected).equals(expected))throw new IllegalStateException("Incomplete compact clock guard installation");
    }
    private static Map<String,String> clockGuards(JdbcTemplate jdbc,String table,Map<String,String> expected){
        var found=new LinkedHashMap<String,String>();
        for(var row:jdbc.queryForList("SELECT trigger_name,action_timing,event_manipulation FROM information_schema.triggers WHERE trigger_schema=DATABASE() AND event_object_table=?",table)){
            String name=(String)row.get("trigger_name");
            if(expected.containsKey(name))found.put(name,row.get("action_timing")+"/"+row.get("event_manipulation"));
        }
        return found;
    }
}
