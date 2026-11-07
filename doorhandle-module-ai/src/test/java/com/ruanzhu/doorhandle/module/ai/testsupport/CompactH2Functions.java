package com.ruanzhu.doorhandle.module.ai.testsupport;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.SQLException;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * Test-only JSON expressions for H2 business/transaction fixtures. These do not
 * emulate MySQL's storage, triggers, collations or JSON Schema implementation;
 * the admitted ECS MySQL suites remain the database-constraint acceptance gate.
 */
public final class CompactH2Functions {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final Set<String> SCHEMA_KEYWORDS = Set.of("type", "properties", "additionalProperties",
            "required", "enum", "anyOf", "items", "maxItems", "maxLength", "minimum", "maximum", "pattern", "uniqueItems");
    private CompactH2Functions() { }

    public static void install(JdbcTemplate jdbc) throws SQLException {
        try (var connection = jdbc.getDataSource().getConnection()) {
            if (!"H2".equals(connection.getMetaData().getDatabaseProductName()))
                throw new IllegalArgumentException("H2 aliases are only for isolated logic fixtures");
        }
        for (String pair : List.of("UTC_TIMESTAMP:utcTimestamp", "JSON_VALID:jsonValid", "JSON_EXTRACT:jsonExtract",
                "JSON_UNQUOTE:jsonUnquote", "JSON_TYPE:jsonType", "JSON_LENGTH:jsonLength",
                "JSON_CONTAINS_PATH:jsonContainsPath", "JSON_SCHEMA_VALID:jsonSchemaValid", "SHA2:sha2")) {
            String[] names = pair.split(":");
            jdbc.execute("CREATE ALIAS IF NOT EXISTS " + names[0] + " FOR '" + CompactH2Functions.class.getName() + "." + names[1] + "'");
        }
    }

    /** Preserve textual JSON and case-sensitive comparisons without removing CHECKs. */
    public static String adaptJsonColumns(String ddl) {
        StringBuilder result = new StringBuilder(), plain = new StringBuilder();
        for (int i = 0; i < ddl.length();) {
            char c = ddl.charAt(i);
            if (c == '\'') {
                result.append(adaptPlain(plain.toString())); plain.setLength(0);
                StringBuilder literal = new StringBuilder(); boolean closed = false; i++;
                while (i < ddl.length()) {
                    c = ddl.charAt(i++);
                    if (c == '\'') {
                        if (i < ddl.length() && ddl.charAt(i) == '\'') { literal.append('\''); i++; }
                        else { closed = true; break; }
                    } else if (c == '\\' && i < ddl.length()) {
                        char escaped = ddl.charAt(i++);
                        literal.append(switch (escaped) {
                            case 'n' -> '\n'; case 'r' -> '\r'; case 't' -> '\t'; case 'b' -> '\b';
                            case '0' -> '\0'; case 'Z' -> (char) 26; default -> escaped;
                        });
                    } else literal.append(c);
                }
                if (!closed) throw new IllegalArgumentException("Unterminated MySQL fixture SQL literal");
                result.append('\'').append(literal.toString().replace("'", "''")).append('\'');
            } else if (ddl.startsWith("--", i) || ddl.startsWith("/*", i)) {
                result.append(adaptPlain(plain.toString())); plain.setLength(0);
                int end = ddl.startsWith("--", i) ? ddl.indexOf('\n', i) : ddl.indexOf("*/", i + 2);
                if (end < 0) end = ddl.length();
                else if (ddl.startsWith("/*", i)) end += 2;
                result.append(ddl, i, end); i = end;
            } else { plain.append(c); i++; }
        }
        return result.append(adaptPlain(plain.toString())).toString();
    }

    private static String adaptPlain(String sql) {
        return sql.replaceAll("(?i)\\bAS\\s+JSON\\s*\\)", "AS VARCHAR)")
                .replaceAll("(?i)\\b([a-z_][a-z0-9_]*)\\s+JSON\\b", "$1 LONGTEXT")
                .replaceAll("(?i)\\bBINARY\\s+", "")
                .replace("<=>", " IS NOT DISTINCT FROM ");
    }

    public static LocalDateTime utcTimestamp() { return LocalDateTime.now(ZoneOffset.UTC); }
    public static LocalDateTime utcTimestamp(int precision) { return utcTimestamp(); }
    public static String sha2(String value, Integer bits) throws Exception {
        if (value == null || bits == null) return null;
        if (bits != 256) throw new IllegalArgumentException("Fixture SHA2 supports the pinned SHA-256 protocol only");
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
    }
    public static boolean jsonValid(String value) {
        try { return value != null && JSON.readTree(value) != null; }
        catch (Exception invalid) { return false; }
    }
    public static String jsonExtract(String value, String path) throws Exception {
        if (value == null || path == null) return null;
        JsonNode node = at(JSON.readTree(value), path);
        return node == null ? null : node.toString();
    }
    public static String jsonUnquote(String value) throws Exception {
        if (value == null) return null;
        JsonNode node;
        try { node = JSON.readTree(value); }
        catch (com.fasterxml.jackson.core.JsonProcessingException notQuotedJson) { return value; }
        if (node == null) return value;
        return node.isTextual() ? node.textValue() : node.toString();
    }
    public static String jsonType(String value) throws Exception {
        if (value == null) return null;
        JsonNode node = JSON.readTree(value);
        if (node.isNull()) return "NULL";
        if (node.isBoolean()) return "BOOLEAN";
        if (node.isTextual()) return "STRING";
        if (node.isObject()) return "OBJECT";
        if (node.isArray()) return "ARRAY";
        return node.isIntegralNumber() ? "INTEGER" : "DOUBLE";
    }
    public static Integer jsonLength(String value, String... path) throws Exception {
        if (value == null) return null;
        if (path.length > 1) throw new IllegalArgumentException("Only one JSON_LENGTH path is supported");
        JsonNode node = JSON.readTree(value);
        if (path.length == 1) node = at(node, path[0]);
        return node == null ? null : node.isContainerNode() ? node.size() : 1;
    }
    public static Integer jsonContainsPath(String value, String mode, String... paths) throws Exception {
        if (value == null || mode == null) return null;
        if ((!"all".equals(mode) && !"one".equals(mode)) || paths.length == 0)
            throw new IllegalArgumentException("Explicit JSON_CONTAINS_PATH mode and paths required");
        JsonNode node = JSON.readTree(value); boolean all = true, any = false;
        for (String path : paths) {
            if (path == null) return null;
            boolean present = at(node, path) != null; all &= present; any |= present;
        }
        return ("all".equals(mode) ? all : any) ? 1 : 0;
    }

    private static JsonNode at(JsonNode node, String path) {
        if (path == null || !path.startsWith("$")) throw new IllegalArgumentException("Explicit JSON path required");
        for (int i = 1; i < path.length();) {
            if (path.charAt(i) == '.') {
                int begin = ++i;
                while (i < path.length() && (Character.isLetterOrDigit(path.charAt(i)) || path.charAt(i) == '_')) i++;
                if (begin == i) throw new IllegalArgumentException("Unsupported fixture JSON path");
                node = node != null && node.isObject() ? node.get(path.substring(begin, i)) : null;
            } else if (path.charAt(i) == '[') {
                int end = path.indexOf(']', i + 1);
                if (end < 0 || !path.substring(i + 1, end).matches("0|[1-9][0-9]*"))
                    throw new IllegalArgumentException("Unsupported fixture JSON array path");
                int index = Integer.parseInt(path.substring(i + 1, end));
                node = node != null && node.isArray() ? node.get(index) : null; i = end + 1;
            } else throw new IllegalArgumentException("Unsupported fixture JSON path syntax");
        }
        return node;
    }

    public static Integer jsonSchemaValid(String schema, String document) throws Exception {
        if (schema == null || document == null) return null;
        JsonNode specification = JSON.readTree(schema);
        requireSupportedSchema(specification);
        return matches(specification, JSON.readTree(document)) ? 1 : 0;
    }

    private static void requireSupportedSchema(JsonNode schema) {
        if (!schema.isObject()) throw new IllegalArgumentException("Fixture schema must be an object");
        schema.fieldNames().forEachRemaining(key -> {
            if (!SCHEMA_KEYWORDS.contains(key)) throw new IllegalArgumentException("Unsupported fixture schema keyword: " + key);
        });
        if (schema.has("properties")) {
            if (!schema.get("properties").isObject()) throw new IllegalArgumentException("Schema properties must be an object");
            schema.get("properties").elements().forEachRemaining(CompactH2Functions::requireSupportedSchema);
        }
        if (schema.has("anyOf")) {
            if (!schema.get("anyOf").isArray() || schema.get("anyOf").isEmpty()) throw new IllegalArgumentException("Explicit anyOf branches required");
            schema.get("anyOf").forEach(CompactH2Functions::requireSupportedSchema);
        }
        if (schema.has("items")) requireSupportedSchema(schema.get("items"));
        if (schema.has("additionalProperties") && !schema.get("additionalProperties").isBoolean())
            throw new IllegalArgumentException("Only boolean additionalProperties is supported");
        if (schema.has("type")) {
            JsonNode types = schema.get("type");
            if (types.isArray() && !types.isEmpty()) types.forEach(CompactH2Functions::requireType);
            else requireType(types);
        }
        if (schema.has("pattern")) {
            if (!schema.get("pattern").isTextual()) throw new IllegalArgumentException("Schema pattern must be a string");
            Pattern.compile(schema.get("pattern").textValue());
        }
        for (String key : List.of("required", "enum"))
            if (schema.has(key) && (!schema.get(key).isArray() || schema.get(key).isEmpty()))
                throw new IllegalArgumentException("Schema " + key + " must be a nonempty array");
        if (schema.has("required")) for (JsonNode field : schema.get("required"))
            if (!field.isTextual()) throw new IllegalArgumentException("Required property names must be strings");
        for (String key : List.of("maxItems", "maxLength"))
            if (schema.has(key) && (!schema.get(key).isIntegralNumber() || schema.get(key).longValue() < 0))
                throw new IllegalArgumentException("Schema " + key + " must be nonnegative integer");
        for (String key : List.of("minimum", "maximum"))
            if (schema.has(key) && !schema.get(key).isNumber()) throw new IllegalArgumentException("Numeric schema bound required");
        if (schema.has("uniqueItems") && !schema.get("uniqueItems").isBoolean())
            throw new IllegalArgumentException("Boolean uniqueItems required");
    }
    private static void requireType(JsonNode type) {
        if (!type.isTextual() || !Set.of("object", "array", "string", "number", "integer", "boolean", "null").contains(type.textValue()))
            throw new IllegalArgumentException("Unsupported fixture schema type");
    }

    private static boolean matches(JsonNode schema, JsonNode value) {
        if (value == null) return false;
        if (schema.has("anyOf")) {
            boolean accepted = false;
            for (JsonNode branch : schema.get("anyOf")) accepted |= matches(branch, value);
            if (!accepted) return false;
        }
        if (schema.has("type")) {
            JsonNode type = schema.get("type"); boolean accepted = false;
            if (type.isArray()) { for (JsonNode option : type) accepted |= hasType(value, option.textValue()); }
            else accepted = hasType(value, type.textValue());
            if (!accepted) return false;
        }
        if (schema.has("enum")) {
            boolean accepted = false;
            for (JsonNode option : schema.get("enum"))
                accepted |= value.isNumber() && option.isNumber()
                        ? value.decimalValue().compareTo(option.decimalValue()) == 0 : value.equals(option);
            if (!accepted) return false;
        }
        if (value.isObject()) {
            JsonNode properties = schema.path("properties");
            if (schema.has("required")) for (JsonNode field : schema.get("required")) if (!value.has(field.textValue())) return false;
            var names = value.fieldNames();
            while (names.hasNext()) {
                String name = names.next();
                if (properties.has(name)) { if (!matches(properties.get(name), value.get(name))) return false; }
                else if (schema.has("additionalProperties") && !schema.get("additionalProperties").booleanValue()) return false;
            }
        }
        if (value.isTextual()) {
            String text = value.textValue();
            if (schema.has("maxLength") && text.codePointCount(0, text.length()) > schema.get("maxLength").intValue()) return false;
            if (schema.has("pattern") && !Pattern.compile(schema.get("pattern").textValue()).matcher(text).find()) return false;
        }
        if (value.isNumber()) {
            BigDecimal number = value.decimalValue();
            if (schema.has("minimum") && number.compareTo(schema.get("minimum").decimalValue()) < 0) return false;
            if (schema.has("maximum") && number.compareTo(schema.get("maximum").decimalValue()) > 0) return false;
        }
        if (value.isArray()) {
            if (schema.has("maxItems") && value.size() > schema.get("maxItems").intValue()) return false;
            Set<JsonNode> seen = new HashSet<>();
            for (JsonNode element : value) {
                if (schema.path("uniqueItems").asBoolean(false) && !seen.add(element)) return false;
                if (schema.has("items") && !matches(schema.get("items"), element)) return false;
            }
        }
        return true;
    }
    private static boolean hasType(JsonNode value, String type) {
        return switch (type) {
            case "object" -> value.isObject(); case "array" -> value.isArray(); case "string" -> value.isTextual();
            case "boolean" -> value.isBoolean(); case "null" -> value.isNull(); case "number" -> value.isNumber();
            case "integer" -> value.isNumber() && value.decimalValue().stripTrailingZeros().scale() <= 0;
            default -> throw new IllegalArgumentException("Unsupported fixture schema type");
        };
    }
}
