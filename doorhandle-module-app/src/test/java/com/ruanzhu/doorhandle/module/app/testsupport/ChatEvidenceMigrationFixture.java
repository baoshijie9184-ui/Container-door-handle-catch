package com.ruanzhu.doorhandle.module.app.testsupport;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;
import org.springframework.jdbc.core.JdbcTemplate;

/** Two already admitted empty ECS schemas, actual V44/V45/V66 and actual 29-table target DDL. */
public final class ChatEvidenceMigrationFixture implements AutoCloseable {
    private final DualSchemaCopyMySqlFixture schemas;
    public ChatEvidenceMigrationFixture() throws Exception {
        var targetTables=new HashSet<String>();
        for(String file:List.of("10-core.sql","20-content.sql","25-agent.sql","30-operations.sql")) {
            var matcher=Pattern.compile("(?m)^CREATE TABLE ([a-z_]+) ").matcher(Files.readString(Path.of("../sql/mysql/compact/baseline",file)));
            while(matcher.find())targetTables.add(matcher.group(1));
        }
        schemas=new DualSchemaCopyMySqlFixture(System.getProperty("doorhandle.chat-evidence.source.config"),System.getProperty("doorhandle.feature.mysql.config"),"doorhandle_feature_",
                Set.of("agent_message_execution","agent_workspace_turn_snapshot","agent_context_turn"),targetTables);
        try {
            schemas.executeSource(Files.readString(Path.of("../sql/mysql/migration-V66-chat-message-execution.sql")));
            schemas.executeSource(Files.readString(Path.of("../sql/mysql/migration-V45-workspace-turn-snapshot.sql")));
            var source=Files.readString(Path.of("../sql/mysql/migration-V44-agent-durable-context.sql"));
            var turn=Pattern.compile("(?s)CREATE TABLE IF NOT EXISTS agent_context_turn \\(.*?;(?=\\s*(?:CREATE|$))").matcher(source);
            if(!turn.find())throw new IllegalStateException("Actual V44 turn source declaration is missing");
            schemas.executeSource(turn.group());new CompactMySqlFixture(schemas.targetDataSource());
        } catch(Exception error){try{close();}catch(Exception cleanup){error.addSuppressed(cleanup);}throw error;}
    }
    public JdbcTemplate source(){return schemas.source();}
    public JdbcTemplate target(){return schemas.target();}
    public javax.sql.DataSource targetDataSource(){return schemas.targetDataSource();}
    public void migrate(String offset) throws Exception {
        if(offset==null||!offset.matches("[+-][0-9]{2}:[0-9]{2}"))throw new IllegalArgumentException("An evidenced source DATETIME offset is required");
        schemas.executeTarget(Files.readString(Path.of("../sql/mysql/compact/copy/24-chat-evidence.sql")).replace("__SOURCE_SCHEMA__",schemas.sourceName()).replace("__SOURCE_CHAT_OFFSET__",offset));
    }
    public void migrateUnresolved()throws Exception{
        schemas.executeTarget(Files.readString(Path.of("../sql/mysql/compact/copy/24-chat-evidence.sql"))
                .replace("__SOURCE_SCHEMA__",schemas.sourceName()).replace("__SOURCE_CHAT_OFFSET__","UNRESOLVED"));
    }
    public String sourceSnapshotSha256(){return schemas.sourceSnapshotSha256();}
    @Override public void close() throws Exception {schemas.close();}
}
