package com.ruanzhu.doorhandle.module.model.testsupport;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.regex.Pattern;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.support.EncodedResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ScriptUtils;

/** Actual V53 source, compact target, and two pre-provisioned empty schemas on one admitted ECS. */
public final class ModelFileMigrationFixture implements AutoCloseable {
    private final DualSchemaCopyMySqlFixture databases;
    private final Path sql;
    public ModelFileMigrationFixture() throws Exception {
        sql=root().resolve("sql/mysql");
        var parts=new LinkedHashMap<Path,String>();
        Set<String> targetTables=new HashSet<>();
        try(var paths=Files.list(sql.resolve("compact/baseline"))) {
            for(Path part:paths.filter(path->path.getFileName().toString().endsWith(".sql")).sorted().toList()) {
                String text=Files.readString(part);parts.put(part,text);
                var tables=Pattern.compile("(?m)^CREATE TABLE ([a-z_]+)\\s*\\(").matcher(text);
                while(tables.find())targetTables.add(tables.group(1));
            }
        }
        if(targetTables.size()!=29)throw new IllegalStateException("Model file verification requires the complete 29-table candidate");
        databases=new DualSchemaCopyMySqlFixture(System.getProperty("model.file.copy.source-config"),System.getProperty("model.file.copy.target-config"),
                "doorhandle_model_verify_",Set.of("detection_model_file_journal","detection_model_file_retention"),
                targetTables);
        try {
            databases.executeSource(Files.readString(sql.resolve("migration-V53-detection-model-file-journal.sql")));
            try(var connection=targetDataSource().getConnection()) {
                for(var part:parts.entrySet())
                    ScriptUtils.executeSqlScript(connection,new EncodedResource(new ByteArrayResource(part.getValue().getBytes(StandardCharsets.UTF_8)),StandardCharsets.UTF_8),
                            false,false,ScriptUtils.DEFAULT_COMMENT_PREFIX,part.getKey().getFileName().toString().endsWith("-guards.sql")?"$$":";",
                            ScriptUtils.DEFAULT_BLOCK_COMMENT_START_DELIMITER,ScriptUtils.DEFAULT_BLOCK_COMMENT_END_DELIMITER);
            }
        } catch(Exception failure){try{databases.close();}catch(Exception cleanup){failure.addSuppressed(cleanup);}throw failure;}
    }
    private static Path root() {
        for(Path path=Path.of("").toAbsolutePath();path!=null;path=path.getParent())
            if(Files.isRegularFile(path.resolve("sql/mysql/migration-V53-detection-model-file-journal.sql")))return path;
        throw new IllegalStateException("Migration checkout missing");
    }
    public JdbcTemplate source(){return databases.source();}
    public JdbcTemplate target(){return databases.target();}
    public DriverManagerDataSource targetDataSource(){return databases.targetDataSource();}
    public String sourceName(){return databases.sourceName();}
    public String targetName(){return databases.targetName();}
    public void copy() throws Exception {copy("+08:00",sourceName());}
    public void copy(String offset,String sourceName) throws Exception {
        String collation=source().queryForObject("SELECT table_collation FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='detection_model_file_journal'",String.class);
        if(collation==null||!collation.matches("utf8mb4_[a-z0-9_]+"))throw new SecurityException("Unobserved source collation");
        databases.executeTarget(Files.readString(sql.resolve("compact/copy/42-model-file-governance.sql"))
                .replace("__SOURCE_SCHEMA__",sourceName).replace("__SOURCE_MODEL_FILE_OFFSET__",offset)
                .replace("__SOURCE_MODEL_FILE_COLLATION__",collation));
    }
    @Override public void close() throws Exception {databases.close();}
}
