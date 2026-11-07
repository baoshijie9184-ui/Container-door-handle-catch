package com.ruanzhu.doorhandle.module.app.testsupport;

import com.ruanzhu.doorhandle.module.ai.testsupport.CompactH2Functions;
import java.nio.charset.StandardCharsets;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;

/** Exact production DDL on ECS MySQL; documented function adaptations for unit fixtures. */
public final class CompactWorkflowFixture {
    private CompactWorkflowFixture() { }
    public static void install(JdbcTemplate jdbc) throws Exception {
        CompactCoordinationFixture.install(jdbc);
        String ddl=new ClassPathResource("db/compact/005-workflow-runtime.sql").getContentAsString(StandardCharsets.UTF_8);
        try(var connection=jdbc.getDataSource().getConnection()) {
            if("H2".equals(connection.getMetaData().getDatabaseProductName())) {
                CompactH2Functions.install(jdbc);
                ddl=CompactH2Functions.adaptDdl(ddl);
            }
        }
        var populator=new ResourceDatabasePopulator(new ByteArrayResource(ddl.getBytes(StandardCharsets.UTF_8)));
        populator.setSqlScriptEncoding("UTF-8");populator.execute(jdbc.getDataSource());
        jdbc.execute("DROP TABLE IF EXISTS agent_conversation_input_audit");
        jdbc.execute("DROP TABLE IF EXISTS agent_conversation_input");
    }
}
