package com.ruanzhu.doorhandle.module.ai.testsupport;

import java.nio.charset.StandardCharsets;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;

/** Production agent_run and shared audit DDL; never installs the removed journal table. */
public final class CompactAgentJournalFixture {
    private CompactAgentJournalFixture() { }
    public static void install(JdbcTemplate jdbc) throws Exception {
        CompactWorkflowFixture.install(jdbc);
        String ddl=new ClassPathResource("db/compact/006-agent-run.sql").getContentAsString(StandardCharsets.UTF_8)
                .replace("CREATE TABLE agent_run", "CREATE TABLE IF NOT EXISTS agent_run");
        try(var connection=jdbc.getDataSource().getConnection()) {
            if("H2".equals(connection.getMetaData().getDatabaseProductName())) {
                ddl=CompactH2Functions.adaptDdl(ddl);
            }
        }
        new ResourceDatabasePopulator(new ByteArrayResource(ddl.getBytes(StandardCharsets.UTF_8))).execute(jdbc.getDataSource());
        boolean journalForeignKey=false,exportForeignKey=false;
        try(var connection=jdbc.getDataSource().getConnection()) {
            String schema="H2".equals(connection.getMetaData().getDatabaseProductName())?connection.getSchema():null;
            try(var keys=connection.getMetaData().getImportedKeys(connection.getCatalog(),schema,"audit_event")) {
                while(keys.next()){
                    if("fk_audit_journal_run".equalsIgnoreCase(keys.getString("FK_NAME")))journalForeignKey=true;
                    if("fk_audit_research_export_run".equalsIgnoreCase(keys.getString("FK_NAME")))exportForeignKey=true;
                }
            }
        }
        if(!journalForeignKey)jdbc.execute("ALTER TABLE audit_event ADD CONSTRAINT fk_audit_journal_run FOREIGN KEY(owner_user_id,journal_run_id) REFERENCES agent_run(user_id,run_id) ON DELETE RESTRICT");
        if(!exportForeignKey)jdbc.execute("ALTER TABLE audit_event ADD CONSTRAINT fk_audit_research_export_run FOREIGN KEY(owner_user_id,research_export_run_id) REFERENCES agent_run(user_id,run_id) ON DELETE RESTRICT ON UPDATE RESTRICT");
        jdbc.execute("DROP TABLE IF EXISTS agent_run_event");
    }
}
