package com.ruanzhu.doorhandle.module.detection.support;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.support.EncodedResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ScriptUtils;

/** Actual V21/V22/V30 source and complete compact target, in distinct pre-provisioned ECS schemas. */
public final class ReportMigrationFixture implements AutoCloseable {
    private static final Pattern TABLE=Pattern.compile("(?im)^CREATE TABLE(?: IF NOT EXISTS)?\\s+`?([a-z_]+)`?\\s*\\(");
    private final DualSchemaCopyMySqlFixture databases;
    private final Path sql;

    public ReportMigrationFixture() throws Exception {
        sql=root().resolve("sql/mysql");
        var sources=new LinkedHashMap<Path,String>();
        Set<String> sourceTables=new HashSet<>();
        for(String name:List.of("migration-V21-quality-report-approval.sql","migration-V22-agent-report-origin.sql","migration-V30-report-event-delivery.sql")) {
            Path file=sql.resolve(name);String text=Files.readString(file);sources.put(file,text);collectTables(text,sourceTables);
        }
        if(sourceTables.size()!=8)throw new IllegalStateException("Report migration requires the actual eight historical report tables");
        var targets=new LinkedHashMap<Path,String>();
        Set<String> targetTables=new HashSet<>();
        try(var paths=Files.list(sql.resolve("compact/baseline"))) {
            for(Path file:paths.filter(path->path.getFileName().toString().endsWith(".sql")).sorted().toList()) {
                String text=Files.readString(file);targets.put(file,text);collectTables(text,targetTables);
            }
        }
        if(targetTables.size()!=29)throw new IllegalStateException("Report migration verification requires the complete 29-table candidate");
        databases=new DualSchemaCopyMySqlFixture(System.getProperty("report.copy.source-config"),System.getProperty("report.copy.target-config"),
                "doorhandle_detection_verify_",sourceTables,targetTables);
        try {
            for(String text:sources.values())databases.executeSource(text);
            try(var connection=targetDataSource().getConnection()) {
                for(var part:targets.entrySet())
                    ScriptUtils.executeSqlScript(connection,new EncodedResource(new ByteArrayResource(part.getValue().getBytes(StandardCharsets.UTF_8)),StandardCharsets.UTF_8),
                            false,false,ScriptUtils.DEFAULT_COMMENT_PREFIX,part.getKey().getFileName().toString().endsWith("-guards.sql")?"$$":";",
                            ScriptUtils.DEFAULT_BLOCK_COMMENT_START_DELIMITER,ScriptUtils.DEFAULT_BLOCK_COMMENT_END_DELIMITER);
            }
        } catch(Exception failure){try{databases.close();}catch(Exception cleanup){failure.addSuppressed(cleanup);}throw failure;}
    }
    private static void collectTables(String text,Set<String> tables) {
        var matcher=TABLE.matcher(text);while(matcher.find())tables.add(matcher.group(1));
    }
    private static Path root() {
        for(Path path=Path.of("").toAbsolutePath();path!=null;path=path.getParent())
            if(Files.isRegularFile(path.resolve("sql/mysql/migration-V21-quality-report-approval.sql")))return path;
        throw new IllegalStateException("Migration checkout missing");
    }
    public JdbcTemplate source(){return databases.source();}
    public JdbcTemplate target(){return databases.target();}
    public DriverManagerDataSource targetDataSource(){return databases.targetDataSource();}
    public String sourceName(){return databases.sourceName();}
    public String targetName(){return databases.targetName();}
    public void copy(String offset) throws Exception {
        if(offset==null||!offset.matches("[+-][0-9]{2}:[0-9]{2}"))throw new IllegalArgumentException("A numeric source UTC offset is required");
        databases.executeTarget(Files.readString(sql.resolve("compact/copy/34-quality-report-workflow.sql"))
                .replace("__SOURCE_SCHEMA__",sourceName()).replace("__SOURCE_REPORT_OFFSET__",offset));
    }
    @Override public void close() throws Exception {databases.close();}
}
