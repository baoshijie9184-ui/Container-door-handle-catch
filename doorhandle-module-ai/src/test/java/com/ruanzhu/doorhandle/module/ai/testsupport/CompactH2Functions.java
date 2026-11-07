package com.ruanzhu.doorhandle.module.ai.testsupport;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.SQLException;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
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
                "JSON_CONTAINS_PATH:jsonContainsPath", "JSON_SCHEMA_VALID:jsonSchemaValid", "SHA2:sha2",
                "H2_JSON_BOOLEAN_VALUE:jsonBooleanValue")) {
            String[] names = pair.split(":");
            jdbc.execute("CREATE ALIAS IF NOT EXISTS " + names[0] + " FOR '" + CompactH2Functions.class.getName() + "." + names[1] + "'");
        }
    }

    /** Preserve textual JSON and case-sensitive comparisons without removing CHECKs. */
    public static String adaptJsonColumns(String ddl) {
        return adaptSql(ddl, null);
    }

    /** Complete test DDL dialect; production MySQL scripts are never rewritten. */
    public static String adaptDdl(String ddl) {
        return adaptSql(ddl, new DdlContext());
    }

    private static final class DdlContext {
        String table = "";
        final Set<String> booleanColumns = new HashSet<>();
    }

    private static String adaptSql(String ddl, DdlContext context) {
        StringBuilder result = new StringBuilder(), plain = new StringBuilder();
        for (int i = 0; i < ddl.length();) {
            char c = ddl.charAt(i);
            if (c == '\'') {
                result.append(adaptPlain(plain.toString(), context)); plain.setLength(0);
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
                result.append(adaptPlain(plain.toString(), context)); plain.setLength(0);
                int end = ddl.startsWith("--", i) ? ddl.indexOf('\n', i) : ddl.indexOf("*/", i + 2);
                if (end < 0) end = ddl.length();
                else if (ddl.startsWith("/*", i)) end += 2;
                result.append(ddl, i, end); i = end;
            } else { plain.append(c); i++; }
        }
        String adapted = result.append(adaptPlain(plain.toString(), context)).toString();
        return context == null ? adapted : expandGeneratedDependencies(adaptGuardedJsonBooleans(adapted));
    }

    private record GeneratedColumn(int clause, int start, int end, String name, String type, String expression) { }

    /** H2 resolves generated expressions against base columns only, unlike MySQL. */
    private static String expandGeneratedDependencies(String sql) {
        String masked = maskProtectedSql(sql);
        var tables = Pattern.compile("(?i)\\bCREATE\\s+TABLE(?:\\s+IF\\s+NOT\\s+EXISTS)?\\s+`?[a-z_][a-z0-9_]*`?\\s*\\(")
                .matcher(masked);
        StringBuilder result = new StringBuilder(); int position = 0;
        while (tables.find()) {
            int opening = tables.end() - 1, closing = closingParenthesis(sql, opening);
            result.append(sql, position, opening + 1).append(expandGeneratedTable(sql.substring(opening + 1, closing)));
            result.append(')'); position = closing + 1;
            tables.region(position, masked.length());
        }
        return result.append(sql, position, sql.length()).toString();
    }

    private static String maskProtectedSql(String sql) {
        StringBuilder result = new StringBuilder(sql);
        for (int i = 0; i < sql.length();) {
            int end = protectedSqlEnd(sql, i);
            if (end == i) { i++; continue; }
            for (int j = i; j < end; j++)
                if (sql.charAt(j) != '\n' && sql.charAt(j) != '\r') result.setCharAt(j, ' ');
            i = end;
        }
        return result.toString();
    }

    private static int closingParenthesis(String sql, int opening) {
        int depth = 1;
        for (int i = opening + 1; i < sql.length();) {
            int end = protectedSqlEnd(sql, i);
            if (end > i) { i = end; continue; }
            char c = sql.charAt(i);
            if (c == '(') depth++;
            else if (c == ')' && --depth == 0) return i;
            i++;
        }
        throw new IllegalArgumentException("Unclosed fixture DDL expression");
    }

    private static String expandGeneratedTable(String body) {
        List<String> clauses = new ArrayList<>(); int position = 0, depth = 0;
        for (int i = 0; i < body.length();) {
            int end = protectedSqlEnd(body, i);
            if (end > i) { i = end; continue; }
            char c = body.charAt(i);
            if (c == '(') depth++;
            else if (c == ')') depth--;
            else if (c == ',' && depth == 0) { clauses.add(body.substring(position, i)); position = i + 1; }
            i++;
        }
        clauses.add(body.substring(position));
        Map<String, GeneratedColumn> generated = new LinkedHashMap<>();
        var declaration = Pattern.compile("(?i)^\\s*(`?[a-z_][a-z0-9_]*`?)\\s+([a-z_][a-z0-9_]*(?:\\s*\\([0-9 ,]+\\))?)"
                + "\\s+GENERATED\\s+ALWAYS\\s+AS\\s*\\(");
        for (int i = 0; i < clauses.size(); i++) {
            String clause = clauses.get(i), masked = maskProtectedSql(clause);
            var match = declaration.matcher(masked);
            if (!match.find()) {
                if (Pattern.compile("(?i)\\bGENERATED\\s+ALWAYS\\s+AS\\b").matcher(masked).find())
                    throw new IllegalArgumentException("Unsupported fixture generated-column declaration");
                continue;
            }
            int start = match.end(), end = closingParenthesis(clause, start - 1);
            String name = match.group(1).replace("`", "").toLowerCase(Locale.ROOT);
            if (generated.put(name, new GeneratedColumn(i, start, end, name, match.group(2), clause.substring(start, end))) != null)
                throw new IllegalArgumentException("Duplicate fixture generated-column declaration");
        }
        Map<String, String> expanded = new LinkedHashMap<>();
        for (GeneratedColumn column : generated.values()) {
            String clause = clauses.get(column.clause());
            clauses.set(column.clause(), clause.substring(0, column.start())
                    + expandGeneratedExpression(column, generated, expanded) + clause.substring(column.end()));
        }
        return String.join(",", clauses);
    }

    private static String expandGeneratedExpression(GeneratedColumn column, Map<String, GeneratedColumn> generated,
                                                     Map<String, String> expanded) {
        if (expanded.containsKey(column.name())) return expanded.get(column.name());
        String sql = column.expression(); StringBuilder result = new StringBuilder();
        for (int i = 0; i < sql.length();) {
            int protectedEnd = protectedSqlEnd(sql, i);
            if (protectedEnd > i) { result.append(sql, i, protectedEnd); i = protectedEnd; continue; }
            int start = i; char c = sql.charAt(i);
            if (c == '`') {
                i = sql.indexOf('`', start + 1);
                if (i < 0) throw new IllegalArgumentException("Unclosed fixture column identifier");
                i++;
            } else if (Character.isLetter(c) || c == '_') {
                while (i < sql.length() && (Character.isLetterOrDigit(sql.charAt(i)) || sql.charAt(i) == '_' || sql.charAt(i) == '$')) i++;
            } else { result.append(c); i++; continue; }
            String token = sql.substring(start, i), name = token.replace("`", "").toLowerCase(Locale.ROOT);
            GeneratedColumn dependency = generated.get(name);
            int next = i; while (next < sql.length() && Character.isWhitespace(sql.charAt(next))) next++;
            if (dependency == null || next < sql.length() && sql.charAt(next) == '(') { result.append(token); continue; }
            int previous = start - 1; while (previous >= 0 && Character.isWhitespace(sql.charAt(previous))) previous--;
            if (previous >= 0 && sql.charAt(previous) == '.' || next < sql.length() && sql.charAt(next) == '.')
                throw new IllegalArgumentException("Qualified fixture generated dependencies are unsupported");
            // MySQL permits references to earlier generated columns only. This
            // also rejects self references, forward references and cycles.
            if (dependency.clause() >= column.clause())
                throw new IllegalArgumentException("Fixture generated dependency must name an earlier column");
            result.append("CAST((").append(expandGeneratedExpression(dependency, generated, expanded))
                    .append(") AS ").append(dependency.type()).append(')');
        }
        String expression = result.toString(); expanded.put(column.name(), expression); return expression;
    }

    /** Only an existing JSON BOOLEAN type guard admits a typed H2 scalar. */
    private static String adaptGuardedJsonBooleans(String sql) {
        StringBuilder result = new StringBuilder();
        for (int i = 0; i < sql.length();) {
            int protectedEnd = protectedSqlEnd(sql, i);
            if (protectedEnd > i) { result.append(sql, i, protectedEnd); i = protectedEnd; continue; }
            if ((i == 0 || !Character.isJavaIdentifierPart(sql.charAt(i - 1)))
                    && sql.regionMatches(true, i, "JSON_EXTRACT", 0, 12)) {
                int opening = i + 12;
                while (opening < sql.length() && Character.isWhitespace(sql.charAt(opening))) opening++;
                if (opening < sql.length() && sql.charAt(opening) == '(') {
                    int depth = 1, end = opening + 1;
                    while (end < sql.length() && depth > 0) {
                        int skipped = protectedSqlEnd(sql, end);
                        if (skipped > end) { end = skipped; continue; }
                        char current = sql.charAt(end++);
                        if (current == '(') depth++;
                        else if (current == ')') depth--;
                    }
                    if (depth != 0) throw new IllegalArgumentException("Unclosed fixture JSON_EXTRACT expression");
                    String expression = sql.substring(i, end);
                    var comparison = Pattern.compile("(?i)\\s*=\\s*(?:TRUE|FALSE)\\b").matcher(sql).region(end, sql.length());
                    var guard = Pattern.compile("(?i)\\bJSON_TYPE\\s*\\(\\s*(?-i:" + Pattern.quote(expression)
                            + ")\\s*\\)\\s*=\\s*'BOOLEAN'\\s+THEN\\s*$").matcher(sql).region(0, i);
                    if (comparison.lookingAt() && guard.find()) {
                        result.append("H2_JSON_BOOLEAN_VALUE(").append(expression).append(')'); i = end; continue;
                    }
                }
            }
            result.append(sql.charAt(i++));
        }
        return result.toString();
    }

    private static int protectedSqlEnd(String sql, int start) {
        if (sql.charAt(start) == '\'') {
            for (int end = start + 1; end < sql.length(); end++) {
                if (sql.charAt(end) != '\'') continue;
                if (end + 1 < sql.length() && sql.charAt(end + 1) == '\'') end++;
                else return end + 1;
            }
            throw new IllegalArgumentException("Unterminated fixture SQL literal");
        }
        if (sql.startsWith("--", start)) { int end = sql.indexOf('\n', start); return end < 0 ? sql.length() : end; }
        if (sql.startsWith("/*", start)) { int end = sql.indexOf("*/", start + 2); return end < 0 ? sql.length() : end + 2; }
        return start;
    }

    private static String adaptPlain(String sql, DdlContext context) {
        String adapted = sql.replaceAll("(?i)\\bAS\\s+JSON\\s*\\)", "AS VARCHAR)")
                // H2 has no UNSIGNED cast target. DECIMAL(20,0) represents
                // every valid U64 value without narrowing through signed long.
                .replaceAll("(?i)\\bAS\\s+UNSIGNED(?:\\s+INTEGER)?\\s*\\)", "AS DECIMAL(20,0))")
                // Only computed projection storage changes; ordinary unsigned
                // primary keys and AUTO_INCREMENT declarations remain intact.
                .replaceAll("(?i)\\bBIGINT\\s+UNSIGNED(?=\\s+GENERATED\\s+ALWAYS\\s+AS\\b)", "DECIMAL(20,0)")
                .replaceAll("(?i)\\b([a-z_][a-z0-9_]*)\\s+JSON\\b", "$1 LONGTEXT")
                .replaceAll("(?i)\\bBINARY\\s+", "")
                // Generated expressions remain real H2 generated columns.
                // Only MySQL's storage modifier is omitted, never the CASE.
                .replaceAll("(?i)\\)\\s+(?:VIRTUAL|STORED)\\b", ")")
                .replace("<=>", " IS NOT DISTINCT FROM ");
        if (context == null) return adapted;
        StringBuilder result = new StringBuilder(); int position = 0;
        var tables = Pattern.compile("(?i)\\bCREATE\\s+TABLE(?:\\s+IF\\s+NOT\\s+EXISTS)?\\s+`?([a-z_][a-z0-9_]*)").matcher(adapted);
        while (tables.find()) {
            result.append(adaptDdlPlain(adapted.substring(position, tables.start()), context));
            context.table = tables.group(1); context.booleanColumns.clear(); position = tables.start();
        }
        return result.append(adaptDdlPlain(adapted.substring(position), context)).toString();
    }

    private static String adaptDdlPlain(String sql, DdlContext context) {
        String result = sql.replaceAll("(?i)\\s+COLLATE(?:\\s+|=)utf8mb4_[a-z0-9_]+", "")
                .replaceAll("(?i)\\s+CHARACTER\\s+SET(?:\\s+|=)utf8mb4", "")
                .replaceAll("(?i)\\s+ENGINE\\s*=\\s*InnoDB", "")
                .replaceAll("(?i)\\s+ROW_FORMAT\\s*=\\s*DYNAMIC", "")
                .replaceAll("(?i)\\s+DEFAULT\\s+CHARSET\\s*=\\s*utf8mb4", "")
                .replaceAll("(?mi)^[\\t ]*KEY\\s+[^\\n]*(?:\\n|$)", "");
        var booleans = Pattern.compile("(?i)(?:^|[(,])\\s*`?([a-z_][a-z0-9_]*)`?\\s+(?:BOOLEAN|BOOL)\\b").matcher(result);
        while (booleans.find()) context.booleanColumns.add(booleans.group(1));
        // MySQL BOOLEAN is a numeric alias; H2 keeps a distinct BOOLEAN type.
        // Translate only 0/1 predicates on columns declared BOOLEAN in this
        // CREATE TABLE. Literals/comments are handled outside this method.
        for (String column : context.booleanColumns) {
            String identifier = "(?<![a-z0-9_$.`])(?:" + Pattern.quote("`" + column + "`")
                    + "|" + Pattern.quote(column) + ")(?![a-z0-9_$`])";
            result = Pattern.compile("(?i)(" + identifier + "\\s*(?:<>|!=|=)\\s*)([01])(?![a-z0-9_$.])")
                    .matcher(result).replaceAll(match -> java.util.regex.Matcher.quoteReplacement(
                            match.group(1) + (match.group(2).equals("1") ? "TRUE" : "FALSE")));
            result = Pattern.compile("(?i)(" + identifier + "\\s+IN\\s*\\(\\s*)([01](?:\\s*,\\s*[01])*)(\\s*\\))")
                    .matcher(result).replaceAll(match -> java.util.regex.Matcher.quoteReplacement(match.group(1)
                            + match.group(2).replace("0", "FALSE").replace("1", "TRUE") + match.group(3)));
        }
        // MySQL index names are scoped to a table; H2 UNIQUE constraints are
        // schema scoped. Preserve every unique key with a deterministic name.
        var unique = Pattern.compile("(?mi)^([\\t ]*)UNIQUE KEY\\s+`?([a-z_][a-z0-9_]*)`?\\s*(\\([^\\n]+\\))").matcher(result);
        StringBuffer renamed = new StringBuffer();
        while (unique.find()) {
            if (context.table.isEmpty()) throw new IllegalArgumentException("Unique key has no fixture table context");
            unique.appendReplacement(renamed, java.util.regex.Matcher.quoteReplacement(unique.group(1)
                    + "CONSTRAINT h2_" + context.table + "_" + unique.group(2) + " UNIQUE " + unique.group(3)));
        }
        unique.appendTail(renamed);
        return renamed.toString().replaceAll(",\\s*\\)", ")");
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
    public static Boolean jsonBooleanValue(String value) throws Exception {
        if (value == null) return null;
        JsonNode node = JSON.readTree(value);
        return node != null && node.isBoolean() ? node.booleanValue() : null;
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
