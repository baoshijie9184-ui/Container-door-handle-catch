package com.ruanzhu.doorhandle.module.ai.testsupport;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;

/** Exact production DDL on ECS MySQL; documented function adaptations for unit fixtures. */
public final class CompactWorkflowFixture {
    private static final ObjectMapper JSON=new ObjectMapper();
    private CompactWorkflowFixture() { }
    public static void install(JdbcTemplate jdbc) throws Exception {
        CompactCoordinationFixture.install(jdbc);
        String ddl=new ClassPathResource("db/compact/005-workflow-runtime.sql").getContentAsString(StandardCharsets.UTF_8);
        try(var connection=jdbc.getDataSource().getConnection()) {
            if("H2".equals(connection.getMetaData().getDatabaseProductName())) {
                for(String pair:new String[]{"UTC_TIMESTAMP:utcTimestamp","JSON_VALID:jsonValid","JSON_EXTRACT:jsonExtract","JSON_UNQUOTE:jsonUnquote"}){
                    var names=pair.split(":");jdbc.execute("CREATE ALIAS IF NOT EXISTS "+names[0]+" FOR '"+CompactWorkflowFixture.class.getName()+"."+names[1]+"'");
                }
                ddl=ddl.replace(" COLLATE utf8mb4_bin","").replace(" COLLATE utf8mb4_0900_ai_ci","").replace(" COLLATE utf8mb4_unicode_ci","")
                    .replace(" VIRTUAL","").replace(" STORED","").replaceAll(" ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin","")
                    .replaceAll("(?m)^(\\s*)UNIQUE KEY (\\w+)\\s*(\\([^\\n]+\\))","$1CONSTRAINT $2 UNIQUE $3")
                    .replaceAll("(?m)^\\s*KEY [^\\n]+\\n","").replaceAll(",\\s*\\)",")");
            }
        }
        var populator=new ResourceDatabasePopulator(new ByteArrayResource(ddl.getBytes(StandardCharsets.UTF_8)));
        populator.setSqlScriptEncoding("UTF-8");populator.execute(jdbc.getDataSource());
        jdbc.execute("DROP TABLE IF EXISTS agent_conversation_input_audit");
        jdbc.execute("DROP TABLE IF EXISTS agent_conversation_input");
    }
    public static LocalDateTime utcTimestamp(){return LocalDateTime.now(ZoneOffset.UTC);}
    public static LocalDateTime utcTimestamp(int precision){return utcTimestamp();}
    public static boolean jsonValid(String value){try{return value!=null&&JSON.readTree(value)!=null;}catch(Exception error){return false;}}
    public static String jsonExtract(String value,String path)throws Exception{
        if(value==null||!path.startsWith("$."))return null;
        var node=JSON.readTree(value).get(path.substring(2));return node==null?null:node.toString();
    }
    public static String jsonUnquote(String value)throws Exception{return value==null?null:JSON.readTree(value).asText();}
}
