package com.ruanzhu.doorhandle.module.app.testsupport;

import com.ruanzhu.doorhandle.module.ai.testsupport.CompactH2Functions;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;

/** Installs the production DDL into an already admitted disposable test database. */
public final class CompactCoordinationFixture {
    private CompactCoordinationFixture() { }

    public static void install(JdbcTemplate jdbc) throws Exception {
        String ddl = new ClassPathResource("db/compact/001-coordination-state.sql")
                .getContentAsString(StandardCharsets.UTF_8);
        try (var connection = jdbc.getDataSource().getConnection()) {
            String database = connection.getMetaData().getDatabaseProductName();
            if ("H2".equals(database)) {
                CompactH2Functions.install(jdbc);
                ddl = CompactH2Functions.adaptDdl(ddl);
            } else if (!"MySQL".equals(database)) {
                throw new IllegalArgumentException("Unsupported disposable fixture database");
            }
        }
        var populator = new ResourceDatabasePopulator(
                new ByteArrayResource(ddl.getBytes(StandardCharsets.UTF_8)));
        populator.setSqlScriptEncoding(StandardCharsets.UTF_8.name());
        populator.execute(jdbc.getDataSource());
        // Their absence makes an accidental old SQL path fail instead of passing on compatibility tables.
        for (String legacy : List.of("agent_conversation_input_owner", "agent_workbench_owner",
                "agent_workspace_owner", "agent_research_storage_owner", "agent_skill_download_owner",
                "quality_knowledge_owner")) {
            jdbc.execute("DROP TABLE IF EXISTS " + legacy);
        }
    }
}
