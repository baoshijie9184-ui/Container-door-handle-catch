package com.ruanzhu.doorhandle.module.detection.support;

import com.ruanzhu.doorhandle.module.detection.EcsIsolatedMysql;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.support.EncodedResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ScriptUtils;
import javax.sql.DataSource;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Pattern;

/** Uses only an empty, host/server/account-verified disposable ECS schema. No database-admin credentials. */
public final class ReportMySqlFixture implements AutoCloseable {
    private final DriverManagerDataSource source;
    private final Set<String> ownedTables=new HashSet<>();
    private boolean ownsEmptySchema;

    public ReportMySqlFixture() {
        try {
            source=EcsIsolatedMysql.open(System.getProperty("doorhandle.report.mysql.config"),"doorhandle_detection_verify_");
            // Shared DATETIME values are UTC; report main-table values are explicitly Beijing LocalDateTime.
            source.setUrl(source.getUrl().replace("serverTimezone=Asia/Shanghai","connectionTimeZone=UTC&forceConnectionTimeZoneToSession=true"));
            if(!tables().isEmpty())throw new IllegalStateException("Report fixture requires its own empty ECS schema");
            ownsEmptySchema=true;
        } catch(Exception error) {throw new IllegalStateException("Cannot admit the isolated ECS report fixture",error);}
        try {
            for(String part:new String[]{"10-core.sql","20-content.sql","25-agent.sql","30-operations.sql","35-runtime-guards.sql","36-identity-guards.sql","37-audit-guards.sql","38-quota-guards.sql","39-workflow-guards.sql","40-relations.sql"})
                install(Path.of("../sql/mysql/compact/baseline",part),part.endsWith("-guards.sql")?"$$":";");
        } catch(Exception error) {close();throw new IllegalStateException("Cannot create report compact-schema fixture",error);}
    }
    public DataSource source(){return source;}

    private void install(Path file,String separator) throws Exception {
        var matcher=Pattern.compile("(?im)^CREATE TABLE(?: IF NOT EXISTS)?\\s+([a-z_]+)\\s*\\(").matcher(Files.readString(file));
        while(matcher.find())ownedTables.add(matcher.group(1));
        try(var connection=source.getConnection()) {
            ScriptUtils.executeSqlScript(connection,new EncodedResource(new FileSystemResource(file),StandardCharsets.UTF_8),false,false,
                    ScriptUtils.DEFAULT_COMMENT_PREFIX,separator,ScriptUtils.DEFAULT_BLOCK_COMMENT_START_DELIMITER,ScriptUtils.DEFAULT_BLOCK_COMMENT_END_DELIMITER);
        }
    }
    private Set<String> tables() {
        return new HashSet<>(new JdbcTemplate(source).queryForList("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()",String.class));
    }
    @Override public void close() {
        if(!ownsEmptySchema)return;
        Set<String> present=tables();
        if(!ownedTables.containsAll(present))throw new IllegalStateException("Unowned table found in report fixture; refusing cleanup");
        try(Connection connection=source.getConnection();var statement=connection.createStatement()) {
            statement.execute("SET FOREIGN_KEY_CHECKS=0");
            try {for(String table:present.stream().sorted().toList())statement.execute("DROP TABLE `"+table+"`");}
            finally {statement.execute("SET FOREIGN_KEY_CHECKS=1");}
            ownsEmptySchema=false;
        } catch(Exception error) {throw new IllegalStateException("Cannot clean owned report fixture tables",error);}
    }
}
