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
public final class CompactActionMySqlFixture implements AutoCloseable {
    private final DriverManagerDataSource targetData,sourceData;
    private final Set<String> targetTables=new HashSet<>(),sourceTables=new HashSet<>();
    private boolean owned;
    private java.util.Map<String,Object> resetShape;
    private boolean resetHealthy;
    private static final Set<String> WORKBENCH_DATA=Set.of("workflow_instance","audit_event","runtime_state");
    public CompactActionMySqlFixture(String property,String prefix,String accountPrefix,boolean migration) throws Exception {
        targetData=EcsIsolatedMysql.open(System.getProperty(property),prefix,accountPrefix);
        sourceData=migration?EcsIsolatedMysql.open(System.getProperty("doorhandle.action.source.config"),"doorhandle_agent_verify_"):null;
        if(!tables(targetData).isEmpty()||(sourceData!=null&&!tables(sourceData).isEmpty()))
            throw new SecurityException("Action fixture requires empty admitted schemas");
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
            if(sourceData!=null)install(sourceData,new ClassPathResource("compact/action-source-evidence.sql").getContentAsString(StandardCharsets.UTF_8),";",sourceTables);
        }catch(Exception error){try{close();}catch(Exception cleanup){error.addSuppressed(cleanup);}throw error;}
    }
    /** Explicit opt-in for the data-only workbench class, never migration/crash/DDL cases. */
    public static CompactActionMySqlFixture forReusableWorkbenchData() throws Exception {
        var fixture=new CompactActionMySqlFixture("workbench.mysql.config","doorhandle_wb_verify_","wb_verify_",false);
        try {
            if(fixture.targetTables.size()!=29)throw new IllegalStateException("Complete compact workbench fixture required");
            fixture.resetShape=resetShape(fixture.targetData,fixture.targetTables,Set.of());
            requireEmptyExcept(fixture.targetData,fixture.targetTables,Set.of());
            fixture.resetHealthy=true;return fixture;
        }catch(Exception failure){try{fixture.close();}catch(Exception cleanup){failure.addSuppressed(cleanup);}throw failure;}
    }
    public void resetWorkbenchData() throws Exception {
        if(!owned||sourceData!=null||resetShape==null||!resetHealthy)
            throw new IllegalStateException("Workbench data reset was not enabled or a previous reset failed");
        resetHealthy=false;
        if(!resetShape.equals(resetShape(targetData,targetTables,WORKBENCH_DATA)))
            throw new SecurityException("Workbench fixture structure or identity changed before data reset");
        requireEmptyExcept(targetData,targetTables,WORKBENCH_DATA);
        truncate(targetData,WORKBENCH_DATA);
        requireEmptyExcept(targetData,targetTables,Set.of());
        if(!resetShape.equals(resetShape(targetData,targetTables,Set.of())))
            throw new SecurityException("Workbench fixture reset did not restore its original structure and counters");
        resetHealthy=true;
    }
    private static java.util.Map<String,Object> resetShape(DriverManagerDataSource data,Set<String> expected,Set<String> mutableCounters)throws Exception {
        try(Connection connection=data.getConnection()) {
            var jdbc=new JdbcTemplate(new org.springframework.jdbc.datasource.SingleConnectionDataSource(connection,true));
            var actual=new HashSet<>(jdbc.queryForList("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE'",String.class));
            if(!actual.equals(expected)||jdbc.queryForObject("SELECT (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type<>'BASE TABLE')+(SELECT COUNT(*) FROM information_schema.routines WHERE routine_schema=DATABASE())+(SELECT COUNT(*) FROM information_schema.events WHERE event_schema=DATABASE())",Long.class)!=0)
                throw new SecurityException("Unowned or missing fixture object before data reset");
            var result=new java.util.LinkedHashMap<String,Object>();
            result.put("identity",jdbc.queryForMap("SELECT DATABASE() db,CURRENT_USER() account,@@server_uuid uuid,@@port port"));
            for(String table:expected.stream().sorted().toList()) {
                String ddl=(String)jdbc.queryForMap("SHOW CREATE TABLE `"+table+"`").get("Create Table");
                if(mutableCounters.contains(table))ddl=ddl.replaceFirst("(?m)^(\\) ENGINE=\\S+) AUTO_INCREMENT=[0-9]+", "$1");
                result.put(table,ddl);
            }
            result.put("triggers",jdbc.queryForList("SELECT trigger_name,event_manipulation,event_object_table,action_order,action_statement,action_orientation,action_timing,sql_mode,definer,character_set_client,collation_connection,database_collation FROM information_schema.triggers WHERE trigger_schema=DATABASE() ORDER BY trigger_name"));
            return result;
        }
    }
    private static void requireEmptyExcept(DriverManagerDataSource data,Set<String> all,Set<String> allowed)throws Exception {
        try(Connection connection=data.getConnection()) {
            var jdbc=new JdbcTemplate(new org.springframework.jdbc.datasource.SingleConnectionDataSource(connection,true));
            for(String table:all.stream().filter(name->!allowed.contains(name)).sorted().toList())
                if(Boolean.TRUE.equals(jdbc.queryForObject("SELECT EXISTS(SELECT 1 FROM `"+table+"` LIMIT 1)",Boolean.class)))
                    throw new SecurityException("Unexpected fixture rows in "+table);
        }
    }
    private static void truncate(DriverManagerDataSource data,Set<String> tables)throws Exception {
        try(Connection connection=data.getConnection();var statement=connection.createStatement()) {
            statement.execute("SET FOREIGN_KEY_CHECKS=0");
            try {for(String table:tables.stream().sorted().toList())statement.execute("TRUNCATE TABLE `"+table+"`");}
            finally {statement.execute("SET FOREIGN_KEY_CHECKS=1");}
        }
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
        String sql=Files.readString(Path.of("../sql/mysql/compact/copy/44-confirmation-actions.sql"))
                .replace("__SOURCE_SCHEMA__",source().queryForObject("SELECT DATABASE()",String.class)).replace("__SOURCE_ACTION_OFFSET__",offset);
        for(String[] pair:new String[][]{{"agent_pending_action","__SOURCE_PENDING_COLLATION__"},{"agent_action_audit","__SOURCE_AUDIT_COLLATION__"}}){
            String collation=source().queryForObject("SELECT table_collation FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=?",String.class,pair[0]);
            if(collation==null||!collation.matches("utf8mb4_[a-z0-9_]+"))throw new SecurityException("Unrecognized source collation");
            sql=sql.replace(pair[1],collation);
        }
        sql=FixtureSourceSnapshot.bind(sql,source(),sourceTables);
        try(Connection connection=targetData.getConnection()){
            connection.setAutoCommit(false);
            try{execute(connection,sql,";");}catch(Exception error){try{connection.rollback();}catch(Exception rollback){error.addSuppressed(rollback);}throw error;}
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
        if(resetShape!=null&&!resetShape.get("identity").equals(jdbc().queryForMap("SELECT DATABASE() db,CURRENT_USER() account,@@server_uuid uuid,@@port port")))
            throw new SecurityException("Reusable workbench fixture identity changed; refusing cleanup");
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
