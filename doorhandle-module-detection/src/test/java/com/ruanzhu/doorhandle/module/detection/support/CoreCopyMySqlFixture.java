package com.ruanzhu.doorhandle.module.detection.support;

import com.ruanzhu.doorhandle.module.detection.EcsIsolatedMysql;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.core.io.support.EncodedResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ScriptUtils;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/** Two existing, empty, host/account/server-verified ECS schemas; never creates databases or grants privileges. */
public final class CoreCopyMySqlFixture implements AutoCloseable {
    private final DriverManagerDataSource source;
    private final DriverManagerDataSource target;
    private final Set<String> sourceTables=new HashSet<>(),targetTables=new HashSet<>();
    private final String sourceName;
    private boolean ownsSchemas;

    public CoreCopyMySqlFixture() throws Exception {
        source=EcsIsolatedMysql.open(System.getProperty("doorhandle.core.copy.source.config"),"doorhandle_detection_verify_");
        target=EcsIsolatedMysql.open(System.getProperty("doorhandle.core.copy.target.config"),"doorhandle_detection_verify_");
        Map<String,Object> left=identity(source),right=identity(target);
        sourceName=String.valueOf(left.get("db"));
        if(sourceName.equals(right.get("db")) || !left.get("uuid").equals(right.get("uuid")) || !left.get("port").equals(right.get("port")))
            throw new SecurityException("Core copy requires two distinct schemas on the same admitted ECS fixture");
        if(!tables(source).isEmpty() || !tables(target).isEmpty())throw new SecurityException("Both core-copy fixture schemas must be empty");
        // Direct schema privileges make source trigger metadata visible; role/global privilege assumptions are not accepted.
        Set<String> privileges=new HashSet<>(new JdbcTemplate(target).queryForList("SELECT privilege_type FROM information_schema.schema_privileges "
                + "WHERE table_schema=? AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1)))",String.class,sourceName));
        if(!privileges.containsAll(Set.of("SELECT","TRIGGER")))throw new SecurityException("Target fixture account requires pre-existing SELECT and TRIGGER metadata access on source schema");
        ownsSchemas=true;
        try {
            install(source,new ClassPathResource("compact/core-source-evidence.sql").getContentAsString(StandardCharsets.UTF_8),";",sourceTables);
            for(String part:new String[]{"10-core.sql","20-content.sql","25-agent.sql","30-operations.sql","35-runtime-guards.sql","36-identity-guards.sql","37-audit-guards.sql","38-quota-guards.sql","39-workflow-guards.sql"})
                install(target,Files.readString(Path.of("../sql/mysql/compact/baseline",part)),part.endsWith("-guards.sql")?"$$":";",targetTables);
            for(String table:sourceTables)new JdbcTemplate(target).queryForObject("SELECT COUNT(*) FROM `"+sourceName+"`.`"+table+"`",Long.class);
        } catch(Exception error) {
            try {close();} catch(Exception cleanup) {error.addSuppressed(cleanup);}
            throw error;
        }
    }
    public JdbcTemplate source(){return new JdbcTemplate(source);}
    public JdbcTemplate target(){return new JdbcTemplate(target);}
    public String sourceName(){return sourceName;}

    /** One connection owns the complete row transaction and rollback. High-water DDL remains reserved after a failure. */
    public void copy() throws Exception {
        String sql=Files.readString(Path.of("../sql/mysql/compact/copy/10-core.sql")).replace("__SOURCE_SCHEMA__",sourceName);
        try(Connection connection=target.getConnection()) {
            connection.setAutoCommit(false);
            try {execute(connection,sql,";");}
            catch(Exception error) {
                try {connection.rollback();} catch(Exception rollback) {error.addSuppressed(rollback);}
                throw error;
            }
        }
    }

    /** Tests supply their known chat source row; production must use the separate, complete agent-domain copy. */
    public void copyChatReferenceAndInstallRelations() throws Exception {
        target().update("INSERT INTO chat_session(id,session_id,username,user_id,title,status,pinned,state_json,checkpoint_version,"
                + "checkpoint_node,checkpoint_exit_reason,checkpoint_updated_at,created_at,updated_at) "
                + "SELECT id,session_id,username,user_id,title,status,pinned,state_json,checkpoint_version,checkpoint_node,checkpoint_exit_reason,"
                + "checkpoint_updated_at,created_at,updated_at FROM `"+sourceName+"`.chat_session");
        install(target,Files.readString(Path.of("../sql/mysql/compact/baseline/40-relations.sql")),";",targetTables);
    }
    private static Map<String,Object> identity(DriverManagerDataSource data) {
        return new JdbcTemplate(data).queryForMap("SELECT DATABASE() db,@@server_uuid uuid,@@port port");
    }
    private static Set<String> tables(DriverManagerDataSource data) {
        return new HashSet<>(new JdbcTemplate(data).queryForList("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()",String.class));
    }
    private static void install(DriverManagerDataSource data,String sql,String separator,Set<String> owned) throws Exception {
        var matcher=Pattern.compile("(?im)^CREATE TABLE(?: IF NOT EXISTS)?\\s+`?([a-z_]+)`?\\s*\\(").matcher(sql);
        while(matcher.find())owned.add(matcher.group(1));
        try(Connection connection=data.getConnection()) {execute(connection,sql,separator);}
    }
    private static void execute(Connection connection,String sql,String separator) {
        ScriptUtils.executeSqlScript(connection,new EncodedResource(new ByteArrayResource(sql.getBytes(StandardCharsets.UTF_8)),StandardCharsets.UTF_8),false,false,
                ScriptUtils.DEFAULT_COMMENT_PREFIX,separator,ScriptUtils.DEFAULT_BLOCK_COMMENT_START_DELIMITER,ScriptUtils.DEFAULT_BLOCK_COMMENT_END_DELIMITER);
    }
    @Override public void close() throws Exception {
        if(!ownsSchemas)return;
        // Check both before deleting either. A foreign object means the configured schemas are no longer exclusively ours.
        Set<String> left=tables(source),right=tables(target);
        if(!sourceTables.containsAll(left) || !targetTables.containsAll(right))throw new SecurityException("Unowned core-copy fixture object found; refusing cleanup");
        clean(target,right);clean(source,left);ownsSchemas=false;
    }
    private static void clean(DriverManagerDataSource data,Set<String> tables) throws Exception {
        try(Connection connection=data.getConnection();var statement=connection.createStatement()) {
            statement.execute("SET FOREIGN_KEY_CHECKS=0");
            try {for(String table:tables.stream().sorted().toList())statement.execute("DROP TABLE `"+table+"`");}
            finally {statement.execute("SET FOREIGN_KEY_CHECKS=1");}
        }
    }
}
