package com.ruanzhu.doorhandle.module.ai.testsupport;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import static org.assertj.core.api.Assertions.*;

/** Execute only through the ECS source suite; H2 results are not MySQL DDL acceptance. */
class CompactH2FunctionsTest {
    private final ObjectMapper json = new ObjectMapper();
    private JdbcTemplate jdbc;
    @BeforeEach void setup() throws Exception {
        jdbc = new JdbcTemplate(new DriverManagerDataSource("jdbc:h2:mem:json-fixture-" + UUID.randomUUID()
                + ";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1", "sa", ""));
        CompactH2Functions.install(jdbc);
    }
    @AfterEach void close() { if (jdbc != null) jdbc.execute("SHUTDOWN"); }

    @Test void nestedNullAndMissingPathsHaveDifferentExistenceAndTypes() throws Exception {
        String value = "{\"sourceKey\":{\"id\":7},\"times\":[null,\"wall\"],\"enabled\":false}";
        assertThat(CompactH2Functions.jsonExtract(value, "$.sourceKey.id")).isEqualTo("7");
        assertThat(CompactH2Functions.jsonExtract(value, "$.times[0]")).isEqualTo("null");
        assertThat(CompactH2Functions.jsonExtract(value, "$.missing")).isNull();
        assertThat(CompactH2Functions.jsonType("null")).isEqualTo("NULL");
        assertThat(CompactH2Functions.jsonContainsPath(value, "all", "$.times[0]", "$.sourceKey.id")).isEqualTo(1);
        assertThat(CompactH2Functions.jsonContainsPath(value, "all", "$.missing")).isZero();
        assertThat(CompactH2Functions.jsonUnquote("\"line\\nnext\"")).isEqualTo("line\nnext");
        assertThat(CompactH2Functions.jsonUnquote("plain")).isEqualTo("plain");
        assertThat(CompactH2Functions.jsonLength(value, "$.times")).isEqualTo(2);
    }

    @Test void schemaRejectsExtraKeysWrongTypesBoundsAndUnknownKeywords() throws Exception {
        String schema = """
            {"type":"object","additionalProperties":false,"required":["id","wall"],
             "properties":{"id":{"type":"integer","minimum":0,"maximum":10},
              "wall":{"type":["string","null"],"maxLength":20}}}
            """;
        assertThat(CompactH2Functions.jsonSchemaValid(schema, "{\"id\":7,\"wall\":null}")).isEqualTo(1);
        for (String bad : new String[]{"{\"id\":11,\"wall\":null}", "{\"id\":\"7\",\"wall\":null}",
                "{\"id\":7,\"wall\":null,\"offset\":\"+08:00\"}", "{\"id\":7}"})
            assertThat(CompactH2Functions.jsonSchemaValid(schema, bad)).as(bad).isZero();
        assertThatThrownBy(() -> CompactH2Functions.jsonSchemaValid("{\"unimplemented\":true}", "{}"))
                .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("Unsupported");
    }

    @Test void mysqlLiteralDecodingAndTextCastsKeepTheActualPatternCheckActive() throws Exception {
        String schema = json.writeValueAsString(Map.of("type", "string", "pattern", "^[0-9]+(\\.[0-9]+)?$"));
        String escaped = schema.replace("\\", "\\\\").replace("'", "''");
        String ddl = "CREATE TABLE fixture_pattern (document JSON NOT NULL, CONSTRAINT ck_pattern CHECK "
                + "(JSON_SCHEMA_VALID('" + escaped + "', CAST(document AS JSON))))";
        String adapted = CompactH2Functions.adaptJsonColumns(ddl);
        assertThat(adapted).contains("CONSTRAINT ck_pattern CHECK", "document LONGTEXT", "AS VARCHAR)");
        jdbc.execute(adapted);
        jdbc.update("INSERT INTO fixture_pattern(document) VALUES(?)", "\"12.3\"");
        assertThatThrownBy(() -> jdbc.update("INSERT INTO fixture_pattern(document) VALUES(?)", "\"12x3\""))
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
    }

    @Test void nativeMysqlModeConstructorsAndSha256WorkWithRegisteredAliases() throws Exception {
        var row = jdbc.queryForMap("SELECT JSON_OBJECT('schemaVersion',1) AS payload,SHA2('abc',256) AS digest,"
                + "REGEXP_LIKE('Ab','^ab$','i') AS matched,UUID() AS id");
        Object payload = row.get("payload");
        var document = payload instanceof byte[] raw ? json.readTree(raw) : json.readTree(payload.toString());
        assertThat(document.get("schemaVersion").intValue()).isEqualTo(1);
        assertThat(row.get("digest")).isEqualTo("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
        assertThat(row.get("matched")).isEqualTo(true);
        assertThat(row.get("id")).isNotNull();
    }

    @Test void generatedColumnsRemainComputedWhileStorageModifiersAndOnlyTheirSyntaxAreAdapted() {
        String source = """
            CREATE TABLE fixture_generated (
              id INT PRIMARY KEY,
              raw JSON NOT NULL,
              calculated VARCHAR(24) GENERATED ALWAYS AS
                (CASE WHEN JSON_TYPE(JSON_EXTRACT(raw,'$.role'))='STRING'
                 THEN JSON_UNQUOTE(JSON_EXTRACT(raw,'$.role')) END) VIRTUAL,
              stored_value INT GENERATED ALWAYS AS (id+1) STORED,
              description VARCHAR(80) DEFAULT ' VIRTUAL and STORED are literal data',
              CONSTRAINT ck_generated CHECK (stored_value>id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
            """;
        String ddl = CompactH2Functions.adaptDdl(source);
        assertThat(ddl).contains("GENERATED ALWAYS AS", " VIRTUAL and STORED are literal data", "CONSTRAINT ck_generated CHECK");
        jdbc.execute(ddl);
        jdbc.update("INSERT INTO fixture_generated(id,raw) VALUES(?,?)", 1, "{\"role\":\"INSPECTOR\"}");
        assertThat(jdbc.queryForMap("SELECT calculated,stored_value FROM fixture_generated WHERE id=1"))
                .containsEntry("calculated", "INSPECTOR").containsEntry("stored_value", 2);
        assertThatThrownBy(() -> jdbc.update("UPDATE fixture_generated SET stored_value=9 WHERE id=1"))
                .isInstanceOf(org.springframework.dao.DataAccessException.class);
    }

    @Test void tableScopedMysqlUniqueNamesRemainIndependentAndEnforcedInH2() {
        jdbc.execute(CompactH2Functions.adaptDdl("""
            CREATE TABLE fixture_left (
              id INT PRIMARY KEY,
              value_id INT,
              UNIQUE KEY same_key (value_id)
            );
            CREATE TABLE fixture_right (
              id INT PRIMARY KEY,
              value_id INT,
              UNIQUE KEY same_key (value_id)
            );
            """));
        jdbc.update("INSERT INTO fixture_left(id,value_id) VALUES(1,10)");
        jdbc.update("INSERT INTO fixture_right(id,value_id) VALUES(1,10)");
        assertThatThrownBy(() -> jdbc.update("INSERT INTO fixture_left(id,value_id) VALUES(2,10)"))
                .isInstanceOf(org.springframework.dao.DuplicateKeyException.class);
        assertThatThrownBy(() -> jdbc.update("INSERT INTO fixture_right(id,value_id) VALUES(2,10)"))
                .isInstanceOf(org.springframework.dao.DuplicateKeyException.class);
    }
}
