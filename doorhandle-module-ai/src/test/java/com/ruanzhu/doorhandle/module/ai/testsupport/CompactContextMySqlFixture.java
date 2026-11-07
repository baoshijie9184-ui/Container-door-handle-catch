package com.ruanzhu.doorhandle.module.ai.testsupport;

import com.ruanzhu.doorhandle.module.ai.EcsIsolatedMysql;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Pattern;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.core.io.support.EncodedResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ScriptUtils;

/** Actual compact DDL in admitted disposable ECS schemas. No local fallback or CREATE DATABASE. */
public final class CompactContextMySqlFixture implements AutoCloseable {
    private final DriverManagerDataSource targetData,sourceData;
    private final Set<String> targetTables=new HashSet<>(),sourceTables=new HashSet<>();
    private boolean owned;
    public CompactContextMySqlFixture(String property,String prefix,String accountPrefix,boolean migration) throws Exception {
        targetData=EcsIsolatedMysql.open(System.getProperty(property),prefix,accountPrefix);
        sourceData=migration?EcsIsolatedMysql.open(System.getProperty("doorhandle.context.source.config"),"doorhandle_agent_verify_"):null;
        if(!tables(targetData).isEmpty()||(sourceData!=null&&!tables(sourceData).isEmpty()))
            throw new SecurityException("Context fixture requires empty admitted schemas");
        if(sourceData!=null){
            var source=source().queryForMap("SELECT DATABASE() db,@@server_uuid uuid");
            var target=jdbc().queryForMap("SELECT DATABASE() db,@@server_uuid uuid");
            if(source.get("db").equals(target.get("db"))||!source.get("uuid").equals(target.get("uuid")))
                throw new SecurityException("Distinct source and target schemas on the same admitted server required");
            var grants=jdbc().queryForList("SELECT privilege_type FROM information_schema.schema_privileges WHERE table_schema=? AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1)))",String.class,source.get("db"));
            if(!grants.containsAll(Set.of("SELECT","TRIGGER")))throw new SecurityException("Pre-existing source SELECT/TRIGGER metadata grants required");
        }
        owned=true;
        try{
            for(String part:CompactBaselineParts.all())
                install(targetData,Files.readString(Path.of("../sql/mysql/compact/baseline",part)),CompactBaselineParts.separator(part),targetTables);
            if(sourceData!=null)install(sourceData,new ClassPathResource("compact/context-source-evidence.sql").getContentAsString(StandardCharsets.UTF_8),";",sourceTables);
        }catch(Exception error){try{close();}catch(Exception cleanup){error.addSuppressed(cleanup);}throw error;}
    }
    public JdbcTemplate jdbc(){return new JdbcTemplate(targetData);}
    public DriverManagerDataSource dataSource(){return targetData;}
    public JdbcTemplate source(){if(sourceData==null)throw new IllegalStateException("No source schema");return new JdbcTemplate(sourceData);}
    public void installTarget(String sql) throws Exception {install(targetData,sql,";",targetTables);}
    public void seedRun(String run,long owner,String session){
        jdbc().update("INSERT INTO agent_run(run_id,user_id,session_id,main_agent,entry_point,request_key,status,default_model,policy_version,instance_id,started_at,heartbeat_at,lease_expires_at) VALUES(?,?,?,'main','CHAT',?,'COMPLETED','fixture','test','fixture',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",run,owner,session,run);
    }
    public void migrate(String offset) throws Exception {
        if(offset==null||!offset.matches("[+-][0-9]{2}:[0-9]{2}"))throw new IllegalArgumentException("Explicit source UTC offset required");
        String sql=Files.readString(Path.of("../sql/mysql/compact/copy/45-context.sql"))
                .replace("__SOURCE_SCHEMA__",source().queryForObject("SELECT DATABASE()",String.class)).replace("__SOURCE_CONTEXT_OFFSET__",offset);
        sql=FixtureSourceSnapshot.bind(sql,source(),sourceTables);
        try(Connection connection=targetData.getConnection()){
            connection.setAutoCommit(false);
            try{execute(connection,"SET @compact_context_source_frozen=1; SET @compact_context_target_frozen=1; "+sql,";");}catch(Exception error){try{connection.rollback();}catch(Exception rollback){error.addSuppressed(rollback);}throw error;}
        }
    }
    private static void install(DriverManagerDataSource data,String sql,String separator,Set<String> ownedTables)throws Exception{
        var matcher=Pattern.compile("(?im)^CREATE TABLE(?: IF NOT EXISTS)?\\s+`?([a-z_]+)`?\\s*\\(").matcher(sql);
        while(matcher.find())ownedTables.add(matcher.group(1));
        try(Connection connection=data.getConnection()){execute(connection,sql,separator);}
    }
    private static void execute(Connection connection,String sql,String separator){
        ScriptUtils.executeSqlScript(connection,new EncodedResource(new ByteArrayResource(sql.getBytes(StandardCharsets.UTF_8)),StandardCharsets.UTF_8),false,false,ScriptUtils.DEFAULT_COMMENT_PREFIX,separator,ScriptUtils.DEFAULT_BLOCK_COMMENT_START_DELIMITER,ScriptUtils.DEFAULT_BLOCK_COMMENT_END_DELIMITER);
    }
    private static Set<String> tables(DriverManagerDataSource data){return new HashSet<>(new JdbcTemplate(data).queryForList("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()",String.class));}
    @Override public void close()throws Exception{
        if(!owned)return;
        Set<String> target=tables(targetData),source=sourceData==null?Set.of():tables(sourceData);
        if(!targetTables.containsAll(target)||!sourceTables.containsAll(source))throw new SecurityException("Unowned tables; refusing cleanup");
        clean(targetData,target);if(sourceData!=null)clean(sourceData,source);owned=false;
    }
    private static void clean(DriverManagerDataSource data,Set<String> tables)throws Exception{
        try(Connection connection=data.getConnection();var statement=connection.createStatement()){
            statement.execute("SET FOREIGN_KEY_CHECKS=0");
            try{for(String table:tables.stream().sorted().toList())statement.execute("DROP TABLE `"+table+"`");}finally{statement.execute("SET FOREIGN_KEY_CHECKS=1");}
        }
    }
}
