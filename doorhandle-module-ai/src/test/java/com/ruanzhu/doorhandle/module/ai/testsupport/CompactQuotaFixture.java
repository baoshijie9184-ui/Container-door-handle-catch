package com.ruanzhu.doorhandle.module.ai.testsupport;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;
import javax.sql.DataSource;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;

/** Actual quota/account constraints in a dedicated, already ECS-admitted empty MySQL schema. */
public final class CompactQuotaFixture implements AutoCloseable {
    private final DataSource source;
    private final Set<String> owned = Set.of("users", "runtime_state", "workflow_instance", "scheduled_plan", "audit_event", "llm_quota", "llm_usage");
    private boolean emptySchemaOwned;

    public CompactQuotaFixture(DataSource admitted) throws Exception {
        source=admitted;
        try(var connection=source.getConnection()) {
            if(!"MySQL".equals(connection.getMetaData().getDatabaseProductName())
                    || connection.getCatalog()==null || !connection.getCatalog().matches("doorhandle_feature_[a-f0-9]{12}"))
                throw new SecurityException("Quota fixture requires its admitted ECS feature schema");
        }
        if(!tables().isEmpty())throw new IllegalStateException("Quota fixture requires an empty schema");
        emptySchemaOwned=true;
        try {
            CompactWorkflowFixture.install(new JdbcTemplate(source));
            table("10-core.sql","users");table("25-agent.sql","llm_quota");table("25-agent.sql","llm_usage");
            String relations=Files.readString(Path.of("../sql/mysql/compact/baseline/40-relations.sql"));
            for(String name:List.of("llm_quota","llm_usage","workflow_instance")) {
                var match=Pattern.compile("(?s)ALTER TABLE "+name+"\\s+.*?;").matcher(relations);
                if(!match.find())throw new IllegalStateException("Actual quota relation is missing: "+name);
                execute(match.group(),";");
            }
            for(String name:List.of("35-runtime-guards.sql","36-identity-guards.sql","37-audit-guards.sql","38-quota-guards.sql","39-workflow-guards.sql"))
                execute(Files.readString(Path.of("../sql/mysql/compact/baseline",name)),"$$");
        } catch(Exception error) {
            try {close();} catch(RuntimeException cleanup) {error.addSuppressed(cleanup);}
            throw error;
        }
    }
    private void table(String part,String name) throws Exception {
        String ddl=Files.readString(Path.of("../sql/mysql/compact/baseline",part));
        var match=Pattern.compile("(?s)CREATE TABLE "+name+" \\(.*?;(?=\\s*(?:--|CREATE|$))").matcher(ddl);
        if(!match.find())throw new IllegalStateException("Actual compact table missing: "+name);
        execute(match.group(),";");
    }
    private void execute(String sql,String separator) {
        var populator=new ResourceDatabasePopulator(new ByteArrayResource(sql.getBytes(StandardCharsets.UTF_8)));
        populator.setSqlScriptEncoding("UTF-8");populator.setSeparator(separator);populator.execute(source);
    }
    private Set<String> tables() {
        return new HashSet<>(new JdbcTemplate(source).queryForList("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()",String.class));
    }
    @Override public void close() {
        if(!emptySchemaOwned)return;
        var present=tables();
        if(!owned.containsAll(present))throw new IllegalStateException("Unowned table in quota fixture; refusing cleanup");
        try(var connection=source.getConnection();var statement=connection.createStatement()) {
            statement.execute("SET FOREIGN_KEY_CHECKS=0");
            try {for(String table:present.stream().sorted().toList())statement.execute("DROP TABLE `"+table+"`");}
            finally {statement.execute("SET FOREIGN_KEY_CHECKS=1");}
            emptySchemaOwned=false;
        } catch(Exception error) {throw new IllegalStateException("Cannot clean owned quota fixture",error);}
    }
}
