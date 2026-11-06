package com.ruanzhu.doorhandle.module.app.testsupport;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;
import org.springframework.jdbc.core.JdbcTemplate;

/** Existing admitted ECS schemas only; actual V38 source and the complete current baseline target. */
public final class WorkspaceMigrationFixture implements AutoCloseable {
    public static final Set<String> SOURCES=Set.of("agent_workspace_owner","agent_workspace_file","agent_workspace_file_ref",
            "agent_workspace_request","agent_session_fork","agent_workspace_audit","agent_workspace_business_ref");
    private final DualSchemaCopyMySqlFixture schemas;
    public WorkspaceMigrationFixture()throws Exception{
        var targetTables=new HashSet<String>();
        for(String file:List.of("10-core.sql","20-content.sql","25-agent.sql","30-operations.sql")){
            var names=Pattern.compile("(?m)^CREATE TABLE ([a-z_]+) ").matcher(Files.readString(Path.of("../sql/mysql/compact/baseline",file)));
            while(names.find())targetTables.add(names.group(1));
        }
        schemas=new DualSchemaCopyMySqlFixture(System.getProperty("doorhandle.workspace.source.config"),System.getProperty("doorhandle.feature.mysql.config"),"doorhandle_feature_",SOURCES,targetTables);
        try{schemas.executeSource(Files.readString(Path.of("../sql/mysql/migration-V38-agent-workspace.sql")));new CompactMySqlFixture(schemas.targetDataSource());}
        catch(Exception error){try{close();}catch(Exception cleanup){error.addSuppressed(cleanup);}throw error;}
    }
    public JdbcTemplate source(){return schemas.source();}
    public JdbcTemplate target(){return schemas.target();}
    public void migrate(String offset)throws Exception{
        if(offset==null||!offset.matches("[+-][0-9]{2}:[0-9]{2}"))throw new IllegalArgumentException("An evidenced source DATETIME offset is required");
        schemas.executeTarget(Files.readString(Path.of("../sql/mysql/compact/copy/43-workspace.sql")).replace("__SOURCE_SCHEMA__",schemas.sourceName()).replace("__SOURCE_WORKSPACE_OFFSET__",offset));
    }
    @Override public void close()throws Exception{schemas.close();}
}
