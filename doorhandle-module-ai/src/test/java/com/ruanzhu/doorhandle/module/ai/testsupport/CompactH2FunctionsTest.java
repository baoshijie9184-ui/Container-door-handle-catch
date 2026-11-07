package com.ruanzhu.doorhandle.module.ai.testsupport;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
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

    @Test void lengthlessMysqlCharCastsPreserveFullOwnerKeysLongTextAndNullWithoutWeakeningChecks() {
        String source = """
            SELECT CAST(? AS CHAR) AS full_text,CAST(NULL AS CHAR) AS null_value,
              CAST('AS CHAR) literal' AS CHAR(40)) AS explicit_length
            /* CAST(91 AS CHAR) is comment data */
            -- CAST(92 AS CHAR) is also comment data
            """;
        String adapted = CompactH2Functions.adaptJsonColumns(source);
        assertThat(adapted).contains("CAST(? AS VARCHAR)", "CAST(NULL AS VARCHAR)",
                "CAST('AS CHAR) literal' AS CHAR(40))", "/* CAST(91 AS CHAR) is comment data */",
                "-- CAST(92 AS CHAR) is also comment data");
        String text = "完整文本".repeat(1024) + " AS CHAR) ";
        assertThat(jdbc.queryForMap(adapted, text)).containsEntry("full_text", text).containsEntry("null_value", null);
        jdbc.execute(CompactH2Functions.adaptDdl("""
            CREATE TABLE fixture_char_binding (
              id INT PRIMARY KEY,
              owner_id DECIMAL(20,0),
              resource_id VARCHAR(40),
              CONSTRAINT ck_char_binding CHECK (
                (owner_id IS NULL AND resource_id IS NULL) OR
                (owner_id IS NOT NULL AND resource_id IS NOT NULL AND resource_id=CAST(owner_id AS CHAR)))
            );
            """));
        String[] owners = {"0", "42", "91", "92", "77", "18446744073709551615"};
        for (int i = 0; i < owners.length; i++) {
            jdbc.update("INSERT INTO fixture_char_binding(id,owner_id,resource_id) VALUES(?,?,?)",
                    i, new BigDecimal(owners[i]), owners[i]);
            String nested = CompactH2Functions.adaptJsonColumns(
                    "SELECT CAST(CAST(JSON_UNQUOTE(JSON_EXTRACT(?,'$.id')) AS DECIMAL(20,0)) AS CHAR)");
            assertThat(jdbc.queryForObject(nested, String.class, "{\"id\":" + owners[i] + "}")).isEqualTo(owners[i]);
        }
        jdbc.update("INSERT INTO fixture_char_binding(id,owner_id,resource_id) VALUES(100,NULL,NULL)");
        assertThatThrownBy(() -> jdbc.update("INSERT INTO fixture_char_binding(id,owner_id,resource_id) VALUES(101,91,'9')"))
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThatThrownBy(() -> jdbc.update("UPDATE fixture_char_binding SET resource_id='4' WHERE owner_id=42"))
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThatThrownBy(() -> jdbc.update("INSERT INTO fixture_char_binding(id,owner_id,resource_id) VALUES(102,NULL,'null')"))
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM fixture_char_binding", Integer.class)).isEqualTo(owners.length + 1);
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

    @Test void unsignedGeneratedProjectionPreservesTheValidU64DomainAndItsChecks() {
        // This fixture accepts the valid U64 business domain. It deliberately
        // does not emulate MySQL's wrap/warning behavior for negative CASTs.
        String ddl = CompactH2Functions.adaptDdl("""
            CREATE TABLE fixture_u64 (
              id INT PRIMARY KEY,
              source_text VARCHAR(40) NOT NULL,
              source_id BIGINT UNSIGNED GENERATED ALWAYS AS
                (CAST(source_text AS UNSIGNED)) VIRTUAL,
              CONSTRAINT ck_u64_text CHECK (REGEXP_LIKE(source_text,'^(0|[1-9][0-9]{0,19})$','c')),
              CONSTRAINT ck_u64_range CHECK (source_id>=0 AND source_id<=18446744073709551615)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """);
        assertThat(ddl).contains("source_id DECIMAL(20,0) GENERATED ALWAYS AS", "CAST(source_text AS DECIMAL(20,0))",
                "CONSTRAINT ck_u64_text CHECK", "CONSTRAINT ck_u64_range CHECK");
        jdbc.execute(ddl);
        String[] valid = {"0", "9223372036854775808", "18446744073709551615"};
        for (int i = 0; i < valid.length; i++) {
            jdbc.update("INSERT INTO fixture_u64(id,source_text) VALUES(?,?)", i, valid[i]);
            assertThat(jdbc.queryForObject("SELECT source_id FROM fixture_u64 WHERE id=?", BigDecimal.class, i))
                    .isEqualByComparingTo(new BigDecimal(valid[i]));
        }
        for (String invalid : new String[]{"-1", "18446744073709551616", "1.5", "not-a-number"})
            assertThatThrownBy(() -> jdbc.update("INSERT INTO fixture_u64(id,source_text) VALUES(99,?)", invalid))
                    .as(invalid).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThatThrownBy(() -> jdbc.update("UPDATE fixture_u64 SET source_id=1 WHERE id=0"))
                .isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM fixture_u64", Integer.class)).isEqualTo(3);
    }

    @Test void unsignedAdaptationLeavesLiteralsCommentsAndOrdinaryIdentityDeclarationsUnchanged() {
        String source = """
            -- CAST(0 AS UNSIGNED) is comment data, not executable syntax
            CREATE TABLE fixture_u64_syntax (
              id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
              source_text VARCHAR(40),
              literal_text VARCHAR(200) DEFAULT ' AS UNSIGNED) BIGINT UNSIGNED GENERATED ALWAYS AS ',
              generated_id BIGINT UNSIGNED GENERATED ALWAYS AS (CAST(source_text AS UNSIGNED INTEGER)) VIRTUAL
            );
            /* AS UNSIGNED) BIGINT UNSIGNED GENERATED ALWAYS AS */
            """;
        String adapted = CompactH2Functions.adaptDdl(source);
        assertThat(adapted).contains("id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY",
                "generated_id DECIMAL(20,0) GENERATED ALWAYS AS (CAST(source_text AS DECIMAL(20,0)))",
                "DEFAULT ' AS UNSIGNED) BIGINT UNSIGNED GENERATED ALWAYS AS '",
                "-- CAST(0 AS UNSIGNED) is comment data, not executable syntax",
                "/* AS UNSIGNED) BIGINT UNSIGNED GENERATED ALWAYS AS */");
    }

    @Test void booleanPredicatesFollowTheDeclaredColumnAndCurrentTableOnly() {
        String source = """
            CREATE TABLE fixture_boolean (
              id INT PRIMARY KEY,
              `enabled` BOOLEAN NOT NULL DEFAULT FALSE,
              enabled_count INT NOT NULL,
              description VARCHAR(80) DEFAULT 'enabled=1 AND enabled IN (0,1)',
              CONSTRAINT ck_boolean CHECK (`enabled` IN (0,1) AND (enabled=1 OR enabled_count=0)),
              CONSTRAINT ck_boolean_false CHECK (enabled<>0 OR id>0)
            );
            -- enabled=1 AND enabled IN (0,1) are comment data
            CREATE TABLE fixture_numeric (
              enabled INT NOT NULL,
              CONSTRAINT ck_numeric CHECK (enabled IN (0,1) AND enabled=1)
            );
            /* enabled=0 AND enabled IN (0,1) are also comment data */
            """;
        String adapted = CompactH2Functions.adaptDdl(source);
        assertThat(adapted).contains("`enabled` BOOLEAN NOT NULL DEFAULT FALSE", "`enabled` IN (FALSE,TRUE)",
                "enabled=TRUE OR enabled_count=0", "enabled<>FALSE OR id>0",
                "DEFAULT 'enabled=1 AND enabled IN (0,1)'",
                "CONSTRAINT ck_numeric CHECK (enabled IN (0,1) AND enabled=1)",
                "-- enabled=1 AND enabled IN (0,1) are comment data",
                "/* enabled=0 AND enabled IN (0,1) are also comment data */");
        jdbc.execute(adapted);
        jdbc.update("INSERT INTO fixture_boolean(id,enabled_count) VALUES(1,0)");
        jdbc.update("INSERT INTO fixture_boolean(id,enabled,enabled_count) VALUES(2,TRUE,7)");
        assertThatThrownBy(() -> jdbc.update("INSERT INTO fixture_boolean(id,enabled,enabled_count) VALUES(3,FALSE,7)"))
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM fixture_boolean", Integer.class)).isEqualTo(2);
    }

    @Test void guardedJsonBooleanAdaptationKeepsJsonTypesAndProtectedSqlDistinct() throws Exception {
        assertThat(CompactH2Functions.jsonExtract("{\"flag\":true}", "$.flag")).isEqualTo("true");
        assertThat(CompactH2Functions.jsonExtract("{\"flag\":\"true\"}", "$.flag")).isEqualTo("\"true\"");
        assertThat(CompactH2Functions.jsonBooleanValue("true")).isTrue();
        assertThat(CompactH2Functions.jsonBooleanValue("false")).isFalse();
        for (String value : new String[]{null, "null", "\"true\"", "\"false\"", "1", "0", "{}", "[]"})
            assertThat(jdbc.queryForObject("SELECT H2_JSON_BOOLEAN_VALUE(?)", Boolean.class, value)).as("JSON scalar %s", value).isNull();
        String expression = "CASE WHEN JSON_TYPE(JSON_EXTRACT(raw,'$.flag'))='BOOLEAN' "
                + "THEN JSON_EXTRACT(raw,'$.flag')=TRUE ELSE NULL END";
        String source = "CREATE TABLE fixture_json_boolean (raw JSON, flag BOOLEAN GENERATED ALWAYS AS (" + expression
                + "), description VARCHAR(500) DEFAULT '" + expression.replace("'", "''") + "');\n-- " + expression;
        String adapted = CompactH2Functions.adaptDdl(source);
        assertThat(adapted).contains("THEN H2_JSON_BOOLEAN_VALUE(JSON_EXTRACT(raw,'$.flag'))=TRUE ELSE NULL END",
                "DEFAULT '" + expression.replace("'", "''") + "'", "-- " + expression);
        assertThat(CompactH2Functions.adaptDdl(expression.replace("THEN JSON_EXTRACT(raw,'$.flag')",
                "THEN JSON_EXTRACT(raw,'$.Flag')"))).doesNotContain("H2_JSON_BOOLEAN_VALUE");
        assertThat(CompactH2Functions.adaptDdl("SELECT JSON_EXTRACT(raw,'$.flag')=TRUE"))
                .doesNotContain("H2_JSON_BOOLEAN_VALUE");
    }

    @Test void generatedDependenciesRemainTypedComputedAndTableScopedAcrossChains() {
        String adapted = CompactH2Functions.adaptDdl("""
            CREATE TABLE fixture_dependency (
              id INT PRIMARY KEY,
              source_text VARCHAR(40),
              root_id BIGINT UNSIGNED GENERATED ALWAYS AS (CAST(source_text AS UNSIGNED)) VIRTUAL,
              middle_id BIGINT UNSIGNED GENERATED ALWAYS AS (CASE WHEN id>0 THEN `root_id` END) VIRTUAL,
              leaf_text VARCHAR(40) GENERATED ALWAYS AS (CAST(middle_id AS CHAR(40))) VIRTUAL,
              literal_text VARCHAR(40) GENERATED ALWAYS AS
                (CASE WHEN source_text='root_id' THEN 'middle_id' ELSE 'leaf_text' END) VIRTUAL,
              /* root_id and middle_id stay comment data */
              UNIQUE KEY same_key (middle_id),
              CONSTRAINT ck_dependency CHECK (root_id>=0 AND root_id<=18446744073709551615)
            );
            CREATE TABLE fixture_dependency_other (
              root_id INT,
              ordinary_copy INT GENERATED ALWAYS AS (root_id+1)
            );
            """);
        assertThat(adapted).contains("THEN CAST((CAST(source_text AS DECIMAL(20,0))) AS DECIMAL(20,0)) END",
                "source_text='root_id' THEN 'middle_id' ELSE 'leaf_text'", "/* root_id and middle_id stay comment data */",
                "ordinary_copy INT GENERATED ALWAYS AS (root_id+1)", "CONSTRAINT ck_dependency CHECK",
                "CONSTRAINT h2_fixture_dependency_same_key UNIQUE");
        jdbc.execute(adapted);
        String[] values = {"0", "9223372036854775808", "18446744073709551615"};
        for (int i = 0; i < values.length; i++) {
            jdbc.update("INSERT INTO fixture_dependency(id,source_text) VALUES(?,?)", i + 1, values[i]);
            assertThat(jdbc.queryForObject("SELECT middle_id FROM fixture_dependency WHERE id=?", BigDecimal.class, i + 1))
                    .isEqualByComparingTo(new BigDecimal(values[i]));
            assertThat(jdbc.queryForObject("SELECT leaf_text FROM fixture_dependency WHERE id=?", String.class, i + 1))
                    .isEqualTo(values[i]);
        }
        jdbc.update("UPDATE fixture_dependency SET source_text='17' WHERE id=1");
        assertThat(jdbc.queryForObject("SELECT leaf_text FROM fixture_dependency WHERE id=1", String.class)).isEqualTo("17");
        jdbc.update("UPDATE fixture_dependency SET source_text=NULL WHERE id=1");
        assertThat(jdbc.queryForObject("SELECT middle_id FROM fixture_dependency WHERE id=1", BigDecimal.class)).isNull();
        assertThat(jdbc.queryForObject("SELECT leaf_text FROM fixture_dependency WHERE id=1", String.class)).isNull();
        assertThatThrownBy(() -> jdbc.update("INSERT INTO fixture_dependency(id,source_text) VALUES(4,?)", values[1]))
                .isInstanceOf(org.springframework.dao.DuplicateKeyException.class);
        assertThatThrownBy(() -> jdbc.update("UPDATE fixture_dependency SET middle_id=1 WHERE id=2"))
                .isInstanceOf(org.springframework.dao.DataAccessException.class);
        jdbc.update("INSERT INTO fixture_dependency_other(root_id) VALUES(4)");
        assertThat(jdbc.queryForObject("SELECT ordinary_copy FROM fixture_dependency_other", Integer.class)).isEqualTo(5);
    }

    @Test void generatedDependenciesRejectSelfForwardCyclesAndUnsupportedDeclarations() {
        for (String columns : new String[]{
                "a INT GENERATED ALWAYS AS (a+1)",
                "a INT GENERATED ALWAYS AS (b+1),b INT GENERATED ALWAYS AS (id+1)",
                "a INT GENERATED ALWAYS AS (b+1),b INT GENERATED ALWAYS AS (a+1)",
                "a INT GENERATED ALWAYS AS (id+1),b INT GENERATED ALWAYS AS (fixture_invalid.a+1)",
                "a INT NOT NULL GENERATED ALWAYS AS (id+1)"})
            assertThatThrownBy(() -> CompactH2Functions.adaptDdl("CREATE TABLE fixture_invalid (id INT," + columns + ");"))
                    .as(columns).isInstanceOf(IllegalArgumentException.class);
    }

    @Test void multipleAlterAddsRetainCompositeKeysActionsChecksAndProtectedCommas() {
        String literal = "ADD x, ADD y; ALTER TABLE ignored ADD z";
        String adapted = CompactH2Functions.adaptDdl("""
            CREATE TABLE fixture_relation_parent (id INT PRIMARY KEY,code INT,UNIQUE(id,code));
            CREATE TABLE fixture_relation_child (a INT,b INT);
            ALTER TABLE fixture_relation_child
              ADD COLUMN marker VARCHAR(160) DEFAULT 'ADD x, ADD y; ALTER TABLE ignored ADD z',
              ADD CONSTRAINT fk_relation_pair FOREIGN KEY(a,b) REFERENCES fixture_relation_parent(id,code)
                ON DELETE CASCADE ON UPDATE CASCADE,
              /* ADD x, ADD y; remains a comment */
              ADD CONSTRAINT ck_relation_pair CHECK (a<>b OR a=0);
            """);
        assertThat(adapted).contains("FOREIGN KEY(a,b) REFERENCES fixture_relation_parent(id,code)",
                "ON DELETE CASCADE ON UPDATE CASCADE", "CONSTRAINT ck_relation_pair CHECK",
                "DEFAULT '" + literal + "'", "/* ADD x, ADD y; remains a comment */");
        assertThat(adapted.lines().filter(line -> line.startsWith("ALTER TABLE fixture_relation_child")).count()).isEqualTo(3);
        jdbc.execute(adapted);
        jdbc.update("INSERT INTO fixture_relation_parent(id,code) VALUES(2,7),(4,4)");
        jdbc.update("INSERT INTO fixture_relation_child(a,b) VALUES(2,7)");
        assertThat(jdbc.queryForObject("SELECT marker FROM fixture_relation_child", String.class)).isEqualTo(literal);
        jdbc.update("UPDATE fixture_relation_parent SET id=3 WHERE id=2");
        assertThat(jdbc.queryForObject("SELECT a FROM fixture_relation_child", Integer.class)).isEqualTo(3);
        assertThatThrownBy(() -> jdbc.update("INSERT INTO fixture_relation_child(a,b) VALUES(4,4)"))
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThatThrownBy(() -> jdbc.update("INSERT INTO fixture_relation_child(a,b) VALUES(9,8)"))
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        jdbc.update("DELETE FROM fixture_relation_parent WHERE id=3");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM fixture_relation_child", Integer.class)).isZero();
    }
}
