package com.ruanzhu.doorhandle.module.ai.testsupport;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import static org.assertj.core.api.Assertions.*;

/** Full current DDL installation on ECS H2; native MySQL/trigger acceptance remains separate. */
class CompactH2FixtureInstallationTest {
    private JdbcTemplate jdbc;
    @BeforeEach void open() throws Exception {
        jdbc = new JdbcTemplate(new DriverManagerDataSource("jdbc:h2:mem:baseline-install-" + UUID.randomUUID()
                + ";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1", "sa", ""));
        CompactH2Functions.install(jdbc);
    }
    @AfterEach void close() { if (jdbc != null) jdbc.execute("SHUTDOWN"); }

    @Test void complete29TableBaselineAndRelationsInstallWithEveryCheckRetained() throws Exception {
        Path baseline = sourceRoot().resolve("sql/mysql/compact/baseline");
        Set<String> expectedTables = new LinkedHashSet<>(); int expectedChecks = 0, expectedForeignKeys = 0;
        for (String file : List.of("10-core.sql", "20-content.sql", "25-agent.sql", "30-operations.sql", "40-relations.sql")) {
            String source = Files.readString(baseline.resolve(file), StandardCharsets.UTF_8);
            var tables = Pattern.compile("(?mi)^CREATE TABLE\\s+([a-z_]+)\\s*\\(").matcher(source);
            while (tables.find()) expectedTables.add(tables.group(1));
            expectedChecks += (int) Pattern.compile("(?mi)^[\\t ]*CONSTRAINT\\s+[a-z_][a-z0-9_]*\\s+CHECK\\s*\\(").matcher(source).results().count();
            expectedForeignKeys += (int) Pattern.compile("(?i)\\bFOREIGN KEY\\s*\\(").matcher(source).results().count();
            install(CompactH2Functions.adaptDdl(source));
        }
        String schema;
        try (var connection = jdbc.getDataSource().getConnection()) { schema = connection.getSchema(); }
        assertThat(expectedTables).hasSize(29);
        assertThat(jdbc.queryForList("SELECT table_name FROM information_schema.tables WHERE table_schema=? AND table_type='BASE TABLE'", String.class, schema))
                .containsExactlyInAnyOrderElementsOf(expectedTables);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.table_constraints WHERE table_schema=? AND constraint_type='CHECK'", Integer.class, schema))
                .isEqualTo(expectedChecks);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.table_constraints WHERE table_schema=? AND constraint_type='FOREIGN KEY'", Integer.class, schema))
                .isEqualTo(expectedForeignKeys);
    }

    @Test void sharedJournalFixtureInstallsItsActualCoordinationAndWorkflowResources() throws Exception {
        CompactAgentJournalFixture.install(jdbc);
        assertThat(jdbc.queryForList("SELECT table_name FROM information_schema.tables WHERE table_schema='public'", String.class))
                .contains("runtime_state", "workflow_instance", "scheduled_plan", "audit_event", "agent_run");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='runtime_state' AND column_name='identity_task_id' AND is_generated='ALWAYS'", Integer.class))
                .isEqualTo(1);
    }

    @Test void sharedContentAndModelFixturesInstallTheCurrentWholeComponentDdl() throws Exception {
        CompactContentFixture.install(jdbc);
        CompactModelConfigurationFixture.install(jdbc);
        assertThat(jdbc.queryForList("SELECT table_name FROM information_schema.tables WHERE table_schema='public'", String.class))
                .contains("content_asset", "content_revision", "content_chunk", "content_link", "llm_configuration", "workflow_instance", "runtime_state", "audit_event");
    }

    private void install(String sql) {
        ResourceDatabasePopulator populator = new ResourceDatabasePopulator(new ByteArrayResource(sql.getBytes(StandardCharsets.UTF_8)));
        populator.setSqlScriptEncoding("UTF-8"); populator.execute(jdbc.getDataSource());
    }
    private static Path sourceRoot() {
        for (Path path = Path.of("").toAbsolutePath(); path != null; path = path.getParent())
            if (Files.isRegularFile(path.resolve("sql/mysql/compact/baseline/10-core.sql"))) return path;
        throw new IllegalStateException("The isolated ECS checkout must retain the actual compact baseline");
    }
}
