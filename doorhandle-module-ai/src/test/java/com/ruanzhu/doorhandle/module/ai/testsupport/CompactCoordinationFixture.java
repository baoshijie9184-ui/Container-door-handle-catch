package com.ruanzhu.doorhandle.module.ai.testsupport;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;

/** Installs the production DDL into an already admitted disposable test database. */
public final class CompactCoordinationFixture {
    private static final ObjectMapper JSON=new ObjectMapper();
    private CompactCoordinationFixture() { }
    public static java.time.LocalDateTime utcTimestamp() { return java.time.LocalDateTime.now(java.time.ZoneOffset.UTC); }
    public static java.time.LocalDateTime utcTimestamp(int precision) { return utcTimestamp(); }

    public static void install(JdbcTemplate jdbc) throws Exception {
        String ddl = new ClassPathResource("db/compact/001-coordination-state.sql")
                .getContentAsString(StandardCharsets.UTF_8);
        try (var connection = jdbc.getDataSource().getConnection()) {
            String database = connection.getMetaData().getDatabaseProductName();
            if ("H2".equals(database)) {
                // Register every expression before the first CHECK/generated column is parsed.
                CompactH2Functions.install(jdbc);
                ddl = CompactH2Functions.adaptDdl(ddl);
            } else if (!"MySQL".equals(database)) {
                throw new IllegalArgumentException("Unsupported disposable fixture database");
            }
        }
        var populator = new ResourceDatabasePopulator(
                new ByteArrayResource(ddl.getBytes(StandardCharsets.UTF_8)));
        populator.setSqlScriptEncoding(StandardCharsets.UTF_8.name());
        populator.execute(jdbc.getDataSource());
        // Their absence makes an accidental old SQL path fail instead of passing on compatibility tables.
        for (String legacy : List.of("agent_conversation_input_owner", "agent_workbench_owner",
                "agent_workspace_owner", "agent_research_storage_owner", "agent_skill_download_owner",
                "quality_knowledge_owner")) {
            jdbc.execute("DROP TABLE IF EXISTS " + legacy);
        }
    }
    public static boolean jsonValid(String value){try{return value!=null&&JSON.readTree(value)!=null;}catch(Exception invalid){return false;}}
    public static String jsonExtract(String value,String path)throws Exception{
        if(value==null||path==null||!path.startsWith("$."))return null;
        var node=JSON.readTree(value).get(path.substring(2));return node==null?null:node.toString();
    }
    public static String jsonType(String value)throws Exception{
        if(value==null)return null;var node=JSON.readTree(value);
        if(node.isNull())return "NULL";if(node.isBoolean())return "BOOLEAN";if(node.isTextual())return "STRING";
        if(node.isObject())return "OBJECT";if(node.isArray())return "ARRAY";
        return node.isIntegralNumber()?"INTEGER":"DOUBLE";
    }
    public static Integer jsonLength(String value)throws Exception{
        if(value==null)return null;var node=JSON.readTree(value);return node.isContainerNode()?node.size():1;
    }
}
