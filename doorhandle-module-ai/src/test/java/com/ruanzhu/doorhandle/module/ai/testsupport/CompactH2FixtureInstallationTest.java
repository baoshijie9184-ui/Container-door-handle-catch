package com.ruanzhu.doorhandle.module.ai.testsupport;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
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
import org.springframework.core.io.ClassPathResource;
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
        jdbc.update("INSERT INTO employee(id,name,employee_number,contact,department,employee_type,gender,hire_date,status) "
                + "VALUES(101,'fixture','fixture-employee','fixture','fixture','DETECTION','UNKNOWN',DATE '2026-01-01','ACTIVE')");
        jdbc.update("INSERT INTO users(username,password) VALUES('history-clear','fixture')");
        jdbc.update("INSERT INTO users(username,password,binding_history_present,binding_version) VALUES('history-present','fixture',TRUE,1)");
        assertThatThrownBy(() -> jdbc.update("INSERT INTO users(username,password,binding_history_present,binding_version) "
                + "VALUES('false-with-version','fixture',FALSE,1)"))
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThatThrownBy(() -> jdbc.update("INSERT INTO users(username,password,binding_history_present,employee_id) "
                + "VALUES('false-with-employee','fixture',FALSE,101)"))
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThatThrownBy(() -> jdbc.update("INSERT INTO users(username,password,binding_history_present,binding_version) "
                + "VALUES('negative-version','fixture',TRUE,-1)"))
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThatThrownBy(() -> jdbc.update("UPDATE users SET binding_history_present=FALSE WHERE username='history-present'"))
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        jdbc.update("INSERT INTO users(username,password,binding_history_present,binding_version,employee_id) "
                + "VALUES('history-bound','fixture',TRUE,1,101)");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM users", Integer.class)).isEqualTo(3);
        assertThat(jdbc.queryForObject("SELECT binding_history_present FROM users WHERE username='history-present'", Boolean.class)).isTrue();
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

    @Test void actualWorkflowYieldColumnReadsOnlyJsonBooleansAndOriginalChecksRejectWrongTypes() throws Exception {
        String source = new ClassPathResource("db/compact/005-workflow-runtime.sql").getContentAsString(StandardCharsets.UTF_8);
        var declarations = source.lines().map(String::strip)
                .filter(line -> line.startsWith("workbench_yield_ready BOOLEAN GENERATED ALWAYS AS")).toList();
        assertThat(declarations).hasSize(1);
        String declaration = declarations.get(0);
        assertThat(declaration).endsWith(",");
        install(CompactH2Functions.adaptDdl("CREATE TABLE fixture_actual_yield (id INT PRIMARY KEY, kind VARCHAR(48) NOT NULL, "
                + "payload_json JSON NOT NULL,\n" + declaration.substring(0, declaration.length() - 1) + "\n);"));
        CompactWorkflowFixture.install(jdbc);
        ObjectMapper json = new ObjectMapper();
        String[] values = {"true", "false", "null", "\"true\"", "\"false\"", "1", "0", "{}", "[]", null};
        for (int i = 0; i < values.length; i++) {
            var document = json.createObjectNode(); var data = document.putObject("data");
            if (values[i] != null) data.set("yieldReady", json.readTree(values[i]));
            jdbc.update("INSERT INTO fixture_actual_yield(id,kind,payload_json) VALUES(?,'WORKBENCH_EXECUTION',?)", i, document.toString());
            Boolean expected = i == 0 ? Boolean.TRUE : i == 1 ? Boolean.FALSE : null;
            assertThat(jdbc.queryForObject("SELECT workbench_yield_ready FROM fixture_actual_yield WHERE id=?", Boolean.class, i))
                    .as("JSON scalar %s", values[i]).isEqualTo(expected);
            for (String field : List.of("username", "role", "runId", "instance", "title", "logicalTaskId", "planRequired",
                    "modelId", "modelConfigVersion", "modelDefault", "approvedPlan", "continuation", "result", "modelConfigurationHistory"))
                data.putNull(field);
            data.put("type", "EXECUTION"); document.put("schemaVersion", 1); document.putArray("presentFields"); document.putNull("legacy");
            String id = "yield-" + i, payload = document.toString();
            String insert = "INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,"
                    + "owner_user_id,resource_type,resource_id,session_id,status,payload_version,payload_json) "
                    + "VALUES(?,'WORKBENCH_EXECUTION','WORKBENCH_ITEM',?,?,1,'WORKBENCH_ITEM',?,'fixture','READY',1,?)";
            if (i <= 2) {
                jdbc.update(insert, id, id, "a".repeat(64), id, payload);
                assertThat(jdbc.queryForObject("SELECT workbench_yield_ready FROM workflow_instance WHERE workflow_id=?", Boolean.class, id))
                        .isEqualTo(expected);
            } else {
                assertThatThrownBy(() -> jdbc.update(insert, id, id, "a".repeat(64), id, payload))
                        .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
            }
        }
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance", Integer.class)).isEqualTo(3);
    }

    @Test void actualAuditGeneratedParentDependencyTracksOriginalCasesUpdatesNullAndU64() throws Exception {
        String source = new ClassPathResource("db/compact/005-workflow-runtime.sql").getContentAsString(StandardCharsets.UTF_8);
        // Select the actual audit_event declarations, not the identically named
        // workflow_instance parent projection earlier in this resource.
        String audit = source.substring(source.indexOf("CREATE TABLE IF NOT EXISTS audit_event"));
        var declarations = audit.lines().map(String::strip)
                .filter(line -> line.startsWith("identity_parent_id BIGINT UNSIGNED GENERATED ALWAYS AS")
                        || line.startsWith("identity_child_parent_id BIGINT UNSIGNED GENERATED ALWAYS AS")).toList();
        assertThat(declarations).hasSize(2);
        String columns = String.join("\n", declarations);
        assertThat(columns).endsWith(",");
        install(CompactH2Functions.adaptDdl("CREATE TABLE fixture_actual_audit_parent (id INT PRIMARY KEY,"
                + "kind VARCHAR(48) NOT NULL,payload_json JSON NOT NULL,\n"
                + columns.substring(0, columns.length() - 1) + "\n);"));
        ObjectMapper json = new ObjectMapper();
        String[] values = {"0", "9223372036854775808", "18446744073709551615"};
        int id = 0;
        for (String kind : List.of("DETECTION_IDENTITY_MAP_ITEM", "DETECTION_IDENTITY_MISSING_NAME",
                "DETECTION_IDENTITY_BINDING_EVENT", "DETECTION_IDENTITY_RECON_ITEM")) {
            String key = kind.equals("DETECTION_IDENTITY_BINDING_EVENT") ? "sourceBatchId"
                    : kind.equals("DETECTION_IDENTITY_RECON_ITEM") ? "reportId" : "batchId";
            boolean child = kind.equals("DETECTION_IDENTITY_MISSING_NAME") || kind.equals("DETECTION_IDENTITY_RECON_ITEM");
            for (String value : values) {
                int row = ++id; String payload = json.createObjectNode().put(key, value).toString();
                jdbc.update("INSERT INTO fixture_actual_audit_parent(id,kind,payload_json) VALUES(?,?,?)", row, kind, payload);
                assertThat(jdbc.queryForObject("SELECT identity_parent_id FROM fixture_actual_audit_parent WHERE id=?", BigDecimal.class, row))
                        .isEqualByComparingTo(new BigDecimal(value));
                BigDecimal actual = jdbc.queryForObject("SELECT identity_child_parent_id FROM fixture_actual_audit_parent WHERE id=?", BigDecimal.class, row);
                if (child) assertThat(actual).isEqualByComparingTo(new BigDecimal(value));
                else assertThat(actual).isNull();
                jdbc.update("UPDATE fixture_actual_audit_parent SET payload_json=? WHERE id=?", json.createObjectNode().put(key, "17").toString(), row);
                assertThat(jdbc.queryForObject("SELECT identity_parent_id FROM fixture_actual_audit_parent WHERE id=?", BigDecimal.class, row))
                        .isEqualByComparingTo("17");
                jdbc.update("UPDATE fixture_actual_audit_parent SET payload_json='{}' WHERE id=?", row);
                assertThat(jdbc.queryForObject("SELECT identity_parent_id FROM fixture_actual_audit_parent WHERE id=?", BigDecimal.class, row)).isNull();
                assertThat(jdbc.queryForObject("SELECT identity_child_parent_id FROM fixture_actual_audit_parent WHERE id=?", BigDecimal.class, row)).isNull();
            }
        }
        jdbc.update("INSERT INTO fixture_actual_audit_parent(id,kind,payload_json) VALUES(99,'OTHER','{\"batchId\":\"7\"}')");
        assertThat(jdbc.queryForObject("SELECT identity_parent_id FROM fixture_actual_audit_parent WHERE id=99", BigDecimal.class)).isNull();
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
