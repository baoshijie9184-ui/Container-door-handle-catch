package com.ruanzhu.doorhandle.module.model.testsupport;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;
import java.util.regex.Pattern;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.support.EncodedResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ScriptUtils;

/** Exact source declarations and public target audit/FK/trigger DDL on two admitted ECS fixture schemas. */
public final class OperationLogCopyFixture implements AutoCloseable {
    private final DualSchemaCopyMySqlFixture databases;
    private final Path sql;
    public OperationLogCopyFixture(String properties,String prefix,boolean model) throws Exception {
        databases=new DualSchemaCopyMySqlFixture(System.getProperty(properties+".source-config"),System.getProperty(properties+".target-config"),prefix,
                model?Set.of("model_management","model_operation_log"):Set.of("operation_audit_log"),
                model?Set.of("model_management","runtime_state","workflow_instance","scheduled_plan","audit_event"):Set.of("runtime_state","workflow_instance","scheduled_plan","audit_event"));
        try {
            sql=root().resolve("sql/mysql");
            if(model) {
                databases.executeSource(table(Files.readString(sql.resolve("schema.sql")),"model_management"));
                databases.executeTarget(table(Files.readString(sql.resolve("compact/baseline/10-core.sql")),"model_management"));
                databases.executeSource(table(Files.readString(sql.resolve("migration-V3-model-lifecycle.sql")),"model_operation_log"));
                var index=Pattern.compile("'(CREATE INDEX idx_model_operation_log_model_time[^']+)'").matcher(Files.readString(sql.resolve("migration-V7-index-and-pool.sql")));
                if(!index.find())throw new IllegalStateException("Actual V7 model-log index evidence missing");
                databases.executeSource(index.group(1)+";");
            } else databases.executeSource(Files.readString(sql.resolve("migration-V15-single-enterprise-shared-data.sql")));
            databases.executeTarget(Files.readString(sql.resolve("compact/baseline/30-operations.sql")));
            try(var connection=targetDataSource().getConnection()) {
                ScriptUtils.executeSqlScript(connection,new EncodedResource(new ByteArrayResource(Files.readString(sql.resolve("compact/baseline/37-audit-guards.sql")).getBytes(StandardCharsets.UTF_8)),StandardCharsets.UTF_8),
                        false,false,ScriptUtils.DEFAULT_COMMENT_PREFIX,"$$",ScriptUtils.DEFAULT_BLOCK_COMMENT_START_DELIMITER,ScriptUtils.DEFAULT_BLOCK_COMMENT_END_DELIMITER);
            }
            if(model) {
                var relation=Pattern.compile("(?s)ALTER TABLE audit_event\\s+ADD CONSTRAINT fk_audit_detection_model\\s+[^;]+;").matcher(Files.readString(sql.resolve("compact/baseline/40-relations.sql")));
                if(!relation.find())throw new IllegalStateException("Actual model audit CASCADE relation missing");
                databases.executeTarget(relation.group());
            }
            FixtureSourceSnapshot.installLegacyClockGuards(target(),sql.resolve("compact/baseline"));
        } catch(Exception failure) {
            try {databases.close();}catch(Exception cleanup){failure.addSuppressed(cleanup);}
            throw failure;
        }
    }
    private static String table(String text,String name) {
        var declaration=Pattern.compile("(?s)CREATE TABLE(?: IF NOT EXISTS)?\\s+`?"+name+"`?\\s*\\(.*?\\) ENGINE[^;]+;").matcher(text);
        if(!declaration.find())throw new IllegalStateException("Source declaration missing: "+name);
        return declaration.group();
    }
    private static Path root() {
        for(Path candidate=Path.of("").toAbsolutePath();candidate!=null;candidate=candidate.getParent())
            if(Files.isRegularFile(candidate.resolve("sql/mysql/compact/copy/40-model-operations.sql")))return candidate;
        throw new IllegalStateException("Migration checkout missing");
    }
    public JdbcTemplate source(){return databases.source();}
    public JdbcTemplate target(){return databases.target();}
    public DriverManagerDataSource targetDataSource(){return databases.targetDataSource();}
    public String sourceName(){return databases.sourceName();}
    public String targetName(){return databases.targetName();}
    public String sourceSnapshotSha256(){return databases.sourceSnapshotSha256();}
    public void copy(String file,String offsetName) throws Exception {copy(file,offsetName,"+08:00",sourceName());}
    public void copy(String file,String offsetName,String offset,String sourceName) throws Exception {
        databases.executeTarget(Files.readString(sql.resolve("compact/copy/"+file)).replace("__SOURCE_SCHEMA__",sourceName).replace(offsetName,offset));
    }
    @Override public void close() throws Exception {databases.close();}
}
