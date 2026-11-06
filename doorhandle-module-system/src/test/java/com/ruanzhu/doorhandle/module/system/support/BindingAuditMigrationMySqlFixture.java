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

/** Two pre-admitted empty ECS schemas; no database creation, grants, or local fallback. */
public final class BindingAuditMigrationMySqlFixture implements AutoCloseable {
    private final DriverManagerDataSource targetData,sourceData;
    private final Set<String> targetTables=new HashSet<>(),sourceTables=new HashSet<>();
    private boolean owned;

    public BindingAuditMigrationMySqlFixture() throws Exception {
        targetData=EcsIsolatedMysql.open(System.getProperty("doorhandle.binding.mysql.config"),"doorhandle_detection_verify_");
        sourceData=EcsIsolatedMysql.open(System.getProperty("doorhandle.binding.source.config"),"doorhandle_detection_verify_");
        if(!tables(targetData).isEmpty()||!tables(sourceData).isEmpty())
            throw new SecurityException("Binding migration requires two empty isolated schemas");
        var sourceIdentity=source().queryForMap("SELECT DATABASE() db,@@server_uuid uuid");
        var targetIdentity=target().queryForMap("SELECT DATABASE() db,@@server_uuid uuid");
        if(sourceIdentity.get("db").equals(targetIdentity.get("db"))||!sourceIdentity.get("uuid").equals(targetIdentity.get("uuid")))
            throw new SecurityException("Source and target must be distinct schemas on the same admitted server");
        var privileges=target().queryForList("SELECT privilege_type FROM information_schema.schema_privileges WHERE table_schema=? "
                +"AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1)))",
                String.class,sourceIdentity.get("db"));
        if(!privileges.containsAll(Set.of("SELECT","TRIGGER")))
            throw new SecurityException("Existing source SELECT/TRIGGER metadata grants are required");
        owned=true;
        try {
            for(String part:new String[]{"10-core.sql","20-content.sql","25-agent.sql","30-operations.sql",
                    "35-runtime-guards.sql","36-identity-guards.sql","37-audit-guards.sql","38-quota-guards.sql","39-workflow-guards.sql","40-relations.sql"})
                install(targetData,Files.readString(Path.of("../sql/mysql/compact/baseline",part)),
                        part.endsWith("-guards.sql")?"$$":";",targetTables);
            install(sourceData,new ClassPathResource("compact/binding-audit-source-evidence.sql")
                    .getContentAsString(StandardCharsets.UTF_8),";",sourceTables);
        } catch(Exception error) {
            try {close();}catch(Exception cleanup){error.addSuppressed(cleanup);}
            throw error;
        }
    }

    public JdbcTemplate target(){return new JdbcTemplate(targetData);}
    public JdbcTemplate source(){return new JdbcTemplate(sourceData);}

    public void installTarget(String sql) throws Exception {install(targetData,sql,";",targetTables);}

    public void migrate(String offset) throws Exception {
        if(offset==null||!offset.matches("[+-][0-9]{2}:[0-9]{2}"))
            throw new IllegalArgumentException("An explicit fixed source UTC offset is required");
        String schema=source().queryForObject("SELECT DATABASE()",String.class);
        String sql=Files.readString(Path.of("../sql/mysql/compact/copy/39-organization-binding-audit.sql"))
                .replace("__SOURCE_SCHEMA__",schema).replace("__SOURCE_BINDING_OFFSET__",offset);
        try(Connection connection=targetData.getConnection()) {
            connection.setAutoCommit(false);
            try {execute(connection,sql,";");}
            catch(Exception error) {
                try {connection.rollback();}catch(Exception rollback){error.addSuppressed(rollback);}
                throw error;
            }
        }
    }

    private static void install(DriverManagerDataSource data,String sql,String separator,Set<String> ownedTables) throws Exception {
        var matcher=Pattern.compile("(?im)^CREATE TABLE(?: IF NOT EXISTS)?\\s+`?([a-z_]+)`?\\s*\\(").matcher(sql);
        while(matcher.find())ownedTables.add(matcher.group(1));
        try(Connection connection=data.getConnection()){execute(connection,sql,separator);}
    }

    private static void execute(Connection connection,String sql,String separator) {
        ScriptUtils.executeSqlScript(connection,new EncodedResource(new ByteArrayResource(sql.getBytes(StandardCharsets.UTF_8)),StandardCharsets.UTF_8),
                false,false,ScriptUtils.DEFAULT_COMMENT_PREFIX,separator,
                ScriptUtils.DEFAULT_BLOCK_COMMENT_START_DELIMITER,ScriptUtils.DEFAULT_BLOCK_COMMENT_END_DELIMITER);
    }

    private static Set<String> tables(DriverManagerDataSource data) {
        return new HashSet<>(new JdbcTemplate(data).queryForList("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()",String.class));
    }

    @Override public void close() throws Exception {
        if(!owned)return;
        Set<String> targetPresent=tables(targetData),sourcePresent=tables(sourceData);
        if(!targetTables.containsAll(targetPresent)||!sourceTables.containsAll(sourcePresent))
            throw new SecurityException("Unowned objects found; refusing binding fixture cleanup");
        clean(targetData,targetPresent);clean(sourceData,sourcePresent);owned=false;
    }

    private static void clean(DriverManagerDataSource data,Set<String> tables) throws Exception {
        try(Connection connection=data.getConnection();var statement=connection.createStatement()) {
            statement.execute("SET FOREIGN_KEY_CHECKS=0");
            try {for(String table:tables.stream().sorted().toList())statement.execute("DROP TABLE `"+table+"`");}
            finally {statement.execute("SET FOREIGN_KEY_CHECKS=1");}
        }
    }
}
