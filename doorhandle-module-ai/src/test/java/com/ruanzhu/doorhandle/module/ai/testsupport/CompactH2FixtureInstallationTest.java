package com.ruanzhu.doorhandle.module.ai.testsupport;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
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
    private static final Map<String, String> INLINE_VERSION_CHECKS = Map.of(
            "organization_department", "version", "device_usage", "version",
            "device_alert", "version", "model_management", "row_version");
    private JdbcTemplate jdbc;
    @BeforeEach void open() throws Exception {
        jdbc = new JdbcTemplate(new DriverManagerDataSource("jdbc:h2:mem:baseline-install-" + UUID.randomUUID()
                + ";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1", "sa", ""));
        CompactH2Functions.install(jdbc);
    }
    @AfterEach void close() { if (jdbc != null) jdbc.execute("SHUTDOWN"); }

    @Test void complete29TableBaselineAndRelationsInstallWithEveryCheckRetained() throws Exception {
        Path baseline = sourceRoot().resolve("sql/mysql/compact/baseline");
        Set<String> expectedTables = new LinkedHashSet<>(), expectedNamedChecks = new LinkedHashSet<>();
        Map<String, String> sourceInlineChecks = new LinkedHashMap<>();
        int expectedForeignKeys = 0;
        for (String file : List.of("10-core.sql", "20-content.sql", "25-agent.sql", "30-operations.sql", "40-relations.sql")) {
            String source = Files.readString(baseline.resolve(file), StandardCharsets.UTF_8);
            var tables = Pattern.compile("(?mi)^CREATE TABLE\\s+([a-z_]+)\\s*\\(").matcher(source);
            while (tables.find()) expectedTables.add(tables.group(1));
            var checks = Pattern.compile("(?mi)^[\\t ]*CONSTRAINT\\s+([a-z_][a-z0-9_]*)\\s+CHECK\\s*\\(").matcher(source);
            while (checks.find()) assertThat(expectedNamedChecks.add(checks.group(1))).isTrue();
            // 四个协同版本字段使用列级 CHECK，不能只统计命名表约束。
            var inline = Pattern.compile("(?mi)^CREATE TABLE\\s+([a-z_]+)\\s*\\(\\s*"
                    + "(version|row_version)\\s+BIGINT\\s+NOT\\s+NULL\\s+DEFAULT\\s+0\\s+CHECK\\s*\\(\\s*\\2\\s*>=\\s*0\\s*\\)\\s*,").matcher(source);
            while (inline.find()) assertThat(sourceInlineChecks.put(inline.group(1), inline.group(2))).isNull();
            expectedForeignKeys += (int) Pattern.compile("(?i)\\bFOREIGN KEY\\s*\\(").matcher(source).results().count();
            install(CompactH2Functions.adaptDdl(source));
        }
        String schema;
        try (var connection = jdbc.getDataSource().getConnection()) { schema = connection.getSchema(); }
        assertThat(expectedTables).hasSize(29);
        assertThat(sourceInlineChecks).isEqualTo(INLINE_VERSION_CHECKS);
        assertThat(jdbc.queryForList("SELECT table_name FROM information_schema.tables WHERE table_schema=? AND table_type='BASE TABLE'", String.class, schema))
                .containsExactlyInAnyOrderElementsOf(expectedTables);
        var installedChecks = jdbc.query("SELECT table_name,constraint_name FROM information_schema.table_constraints "
                        + "WHERE table_schema=? AND constraint_type='CHECK'",
                (row, index) -> Map.entry(row.getString("table_name"), row.getString("constraint_name")), schema);
        assertThat(installedChecks).hasSize(expectedNamedChecks.size() + INLINE_VERSION_CHECKS.size());
        assertThat(installedChecks.stream().map(Map.Entry::getValue).toList()).containsAll(expectedNamedChecks);
        Map<String, String> installedInlineCheckNames = new LinkedHashMap<>();
        for (var check : installedChecks) {
            if (!expectedNamedChecks.contains(check.getValue())) {
                assertThat(installedInlineCheckNames.put(check.getKey(), check.getValue())).isNull();
            }
        }
        assertThat(installedInlineCheckNames.keySet()).containsExactlyInAnyOrderElementsOf(INLINE_VERSION_CHECKS.keySet());
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.table_constraints WHERE table_schema=? AND constraint_type='FOREIGN KEY'", Integer.class, schema))
                .isEqualTo(expectedForeignKeys);
        jdbc.update("INSERT INTO employee(id,name,employee_number,contact,department,employee_type,gender,hire_date,status) "
                + "VALUES(101,'fixture','fixture-employee','fixture','fixture','DETECTION','UNKNOWN',DATE '2026-01-01','ACTIVE')");
        assertInlineVersionChecks(installedInlineCheckNames);
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
        long user = jdbc.queryForObject("SELECT id FROM users WHERE username='history-clear'", Long.class);
        jdbc.update("INSERT INTO chat_project(project_id,username,user_id,name) VALUES('fk-project','history-clear',?,'fixture')", user);
        jdbc.update("INSERT INTO chat_session(session_id,username,user_id,project_id) VALUES('fk-session','history-clear',?,'fk-project')", user);
        jdbc.update("INSERT INTO chat_message(session_id,role,content) VALUES('fk-session','USER','fixture')");
        assertThatThrownBy(() -> jdbc.update("INSERT INTO chat_project(project_id,username,user_id,name) "
                + "VALUES('orphan-project','history-clear',999999,'fixture')"))
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThatThrownBy(() -> jdbc.update("INSERT INTO chat_session(session_id,username,user_id,project_id) "
                + "VALUES('orphan-session','history-clear',?,'missing-project')", user))
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThatThrownBy(() -> jdbc.update("UPDATE users SET id=? WHERE id=?", user + 1000, user))
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThatThrownBy(() -> jdbc.update("UPDATE chat_project SET project_id='restricted-project' WHERE project_id='fk-project'"))
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        jdbc.update("UPDATE users SET username='history-renamed' WHERE id=?", user);
        assertThat(jdbc.queryForObject("SELECT username FROM chat_project WHERE project_id='fk-project'", String.class)).isEqualTo("history-renamed");
        assertThat(jdbc.queryForObject("SELECT username FROM chat_session WHERE session_id='fk-session'", String.class)).isEqualTo("history-renamed");
        jdbc.update("UPDATE chat_session SET session_id='fk-session-renamed' WHERE session_id='fk-session'");
        assertThat(jdbc.queryForObject("SELECT session_id FROM chat_message", String.class)).isEqualTo("fk-session-renamed");
        jdbc.update("DELETE FROM chat_project WHERE project_id='fk-project'");
        assertThat(jdbc.queryForObject("SELECT project_id FROM chat_session WHERE session_id='fk-session-renamed'", String.class)).isNull();
        jdbc.update("INSERT INTO chat_project(project_id,username,user_id,name) VALUES('fk-project-delete','history-renamed',?,'fixture')", user);
        jdbc.update("DELETE FROM users WHERE id=?", user);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM chat_project", Integer.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM chat_session", Integer.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM chat_message", Integer.class)).isZero();
    }

    private void assertInlineVersionChecks(Map<String, String> installedNames) {
        jdbc.update("INSERT INTO organization_department(id,name) VALUES(201,'inline-version-department')");
        jdbc.update("INSERT INTO device_management(id,device_code,device_type,model_name,serial_number,status) "
                + "VALUES(201,'inline-version-device','IMAGE_CAPTURE','fixture','inline-version-serial','IDLE')");
        jdbc.update("INSERT INTO device_usage(id,device_id,device_code,device_type,model_name,serial_number,"
                + "employee_id,employee_name,employee_number,contact,start_time) "
                + "VALUES(201,201,'inline-version-device','IMAGE_CAPTURE','fixture','inline-version-serial',"
                + "101,'fixture','fixture-employee','fixture',TIMESTAMP '2026-01-01 00:00:00')");
        jdbc.update("INSERT INTO device_alert(id,alert_id,device_id,device_code,alert_type,alert_message) "
                + "VALUES(201,'inline-version-alert',201,'inline-version-device','CAPTURE_EXCEPTION','fixture')");
        jdbc.update("INSERT INTO model_management(model_id,model_name,version,model_path) "
                + "VALUES(201,'inline-version-model','v1','fixture')");
        for (var check : INLINE_VERSION_CHECKS.entrySet()) {
            String table = check.getKey(), column = check.getValue();
            String row = table.equals("model_management") ? "model_id=201" : "id=201";
            assertThat(jdbc.queryForObject("SELECT " + column + " FROM " + table + " WHERE " + row, Long.class)).isZero();
            assertThat(jdbc.update("UPDATE " + table + " SET " + column + "=" + column + "+1 WHERE " + row)).isEqualTo(1);
            assertThatThrownBy(() -> jdbc.update("UPDATE " + table + " SET " + column + "=-1 WHERE " + row))
                    .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class)
                    .satisfies(failure -> assertThat(((org.springframework.dao.DataIntegrityViolationException) failure)
                            .getMostSpecificCause().getMessage()).containsIgnoringCase(installedNames.get(table)));
            assertThat(jdbc.queryForObject("SELECT " + column + " FROM " + table + " WHERE " + row, Long.class)).isEqualTo(1L);
        }
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
