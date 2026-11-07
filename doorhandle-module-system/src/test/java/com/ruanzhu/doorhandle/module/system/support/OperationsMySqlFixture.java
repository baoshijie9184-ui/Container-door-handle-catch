package com.ruanzhu.doorhandle.module.system.support;

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
import java.util.Set;
import java.util.regex.Pattern;

/** Owns tables only inside existing empty ECS schemas admitted by host, account, port, UUID and datadir. */
public final class OperationsMySqlFixture implements AutoCloseable {
    private final DriverManagerDataSource target,source;
    private final Set<String> targetTables=new HashSet<>(),sourceTables=new HashSet<>();
    private boolean owned;
    public OperationsMySqlFixture(boolean migration) throws Exception {
        target=EcsIsolatedMysql.open(System.getProperty("doorhandle.operations.mysql.config"),"doorhandle_detection_verify_");
        source=migration?EcsIsolatedMysql.open(System.getProperty("doorhandle.operations.source.config"),"doorhandle_detection_verify_"):null;
        if(!tables(target).isEmpty() || source!=null && !tables(source).isEmpty())throw new SecurityException("Operations fixture requires empty isolated schemas");
        if(source!=null) {
            var left=new JdbcTemplate(source).queryForMap("SELECT DATABASE() db,@@server_uuid uuid");
            var right=new JdbcTemplate(target).queryForMap("SELECT DATABASE() db,@@server_uuid uuid");
            if(left.get("db").equals(right.get("db")) || !left.get("uuid").equals(right.get("uuid")))throw new SecurityException("Migration schemas must be distinct on the same admitted server");
            var privileges=new JdbcTemplate(target).queryForList("SELECT privilege_type FROM information_schema.schema_privileges WHERE table_schema=? "
                    + "AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1)))",String.class,left.get("db"));
            if(!privileges.containsAll(Set.of("SELECT","TRIGGER")))throw new SecurityException("Existing source SELECT/TRIGGER metadata grants are required");
        }
        owned=true;
        try {
            for(String part:new String[]{"10-core.sql","20-content.sql","25-agent.sql","30-operations.sql","35-runtime-guards.sql","36-identity-guards.sql","37-audit-guards.sql","38-quota-guards.sql","39-workflow-guards.sql","40-relations.sql"})
                install(Files.readString(Path.of("../sql/mysql/compact/baseline",part)),part.endsWith("-guards.sql")?"$$":";");
            FixtureSourceSnapshot.installLegacyClockGuards(target(),Path.of("../sql/mysql/compact/baseline"));
            if(source!=null)install(source,new ClassPathResource("compact/operations-source-evidence.sql").getContentAsString(StandardCharsets.UTF_8),";",sourceTables);
        } catch(Exception error) {try {close();}catch(Exception cleanup){error.addSuppressed(cleanup);}throw error;}
    }
    public DriverManagerDataSource dataSource(){return target;}
    public JdbcTemplate target(){return new JdbcTemplate(target);}
    public JdbcTemplate source(){if(source==null)throw new IllegalStateException("No source schema");return new JdbcTemplate(source);}
    public void install(String sql,String separator) throws Exception {install(target,sql,separator,targetTables);}
    public void migrate(String offset) throws Exception {
        if(!offset.matches("[+-][0-9]{2}:[0-9]{2}"))throw new IllegalArgumentException("Explicit source offset required");
        String name=source().queryForObject("SELECT DATABASE()",String.class);
        String sql=Files.readString(Path.of("../sql/mysql/compact/copy/37-operations-file-delivery.sql"))
                .replace("__SOURCE_SCHEMA__",name).replace("__SOURCE_OPERATIONS_OFFSET__",offset);
        sql=FixtureSourceSnapshot.bind(sql,source(),sourceTables);
        try(Connection connection=target.getConnection()) {
            connection.setAutoCommit(false);
            try {execute(connection,sql,";");}
            catch(Exception error) {try {connection.rollback();}catch(Exception rollback){error.addSuppressed(rollback);}throw error;}
        }
    }
    private static void install(DriverManagerDataSource data,String sql,String separator,Set<String> owned) throws Exception {
        var matcher=Pattern.compile("(?im)^CREATE TABLE(?: IF NOT EXISTS)?\\s+`?([a-z_]+)`?\\s*\\(").matcher(sql);
        while(matcher.find())owned.add(matcher.group(1));
        try(Connection connection=data.getConnection()){execute(connection,sql,separator);}
    }
    private static void execute(Connection connection,String sql,String separator) {
        ScriptUtils.executeSqlScript(connection,new EncodedResource(new ByteArrayResource(sql.getBytes(StandardCharsets.UTF_8)),StandardCharsets.UTF_8),false,false,
                ScriptUtils.DEFAULT_COMMENT_PREFIX,separator,ScriptUtils.DEFAULT_BLOCK_COMMENT_START_DELIMITER,ScriptUtils.DEFAULT_BLOCK_COMMENT_END_DELIMITER);
    }
    private static Set<String> tables(DriverManagerDataSource data) {
        return new HashSet<>(new JdbcTemplate(data).queryForList("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()",String.class));
    }
    @Override public void close() throws Exception {
        if(!owned)return;
        var right=tables(target);var left=source==null?Set.<String>of():tables(source);
        if(!targetTables.containsAll(right) || !sourceTables.containsAll(left))throw new SecurityException("Unowned object found; refusing fixture cleanup");
        clean(target,right);if(source!=null)clean(source,left);owned=false;
    }
    private static void clean(DriverManagerDataSource data,Set<String> names) throws Exception {
        try(Connection connection=data.getConnection();var statement=connection.createStatement()) {
            statement.execute("SET FOREIGN_KEY_CHECKS=0");
            try {for(String table:names.stream().sorted().toList())statement.execute("DROP TABLE `"+table+"`");}
            finally {statement.execute("SET FOREIGN_KEY_CHECKS=1");}
        }
    }
}
