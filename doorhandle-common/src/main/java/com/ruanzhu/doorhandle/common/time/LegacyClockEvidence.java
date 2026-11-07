package com.ruanzhu.doorhandle.common.time;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigInteger;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeFormatterBuilder;
import java.time.format.ResolverStyle;
import java.time.temporal.ChronoField;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/** Strict provenance for a retained SQL wall clock whose absolute instant is unknown.
 * The MYSQL_JSON_SHA256_V1 row digest is produced by the reviewed SQL exporter;
 * Jackson serialization must never be substituted for that hash algorithm.
 */
public final class LegacyClockEvidence {
    public static final String PROTOCOL = "doorhandle-legacy-clock-v1";
    public static final String UNRESOLVED = "UNRESOLVED";
    private static final Set<String> KEYS = Set.of("protocol", "status", "sourceTable", "sourceKey",
            "sourceSnapshotSha256", "sourceRowSha256", "sourceWallTimes");
    private static final ObjectMapper JSON = new ObjectMapper()
            .enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);
    private static final DateTimeFormatter WALL_TIME = new DateTimeFormatterBuilder()
            .appendPattern("uuuu-MM-dd HH:mm:ss")
            .optionalStart().appendFraction(ChronoField.NANO_OF_SECOND, 1, 6, true).optionalEnd()
            .toFormatter(java.util.Locale.ROOT).withResolverStyle(ResolverStyle.STRICT);

    private final String sourceTable;
    private final Map<String, Object> sourceKey;
    private final String sourceSnapshotSha256;
    private final String sourceRowSha256;
    private final Map<String, String> sourceWallTimes;

    private LegacyClockEvidence(String table, Map<String, Object> key, String snapshot, String row,
                                Map<String, String> wallTimes) {
        sourceTable = table;
        sourceKey = Collections.unmodifiableMap(new LinkedHashMap<>(key));
        sourceSnapshotSha256 = snapshot;
        sourceRowSha256 = row;
        // A SQL NULL is an original value, so Map.copyOf cannot be used here.
        sourceWallTimes = Collections.unmodifiableMap(new LinkedHashMap<>(wallTimes));
    }

    public static Optional<LegacyClockEvidence> optional(String value, String expectedSourceTable,
                                                        Map<String, ?> expectedSourceKey) {
        return value == null ? Optional.empty() : Optional.of(parse(value, expectedSourceTable, expectedSourceKey));
    }

    public static LegacyClockEvidence parse(String value, String expectedSourceTable,
                                            Map<String, ?> expectedSourceKey) {
        try {
            require(value != null && value.length() <= 65_536 && expectedSourceTable != null
                    && expectedSourceTable.matches("[a-z][a-z0-9_]{0,63}")
                    && expectedSourceKey != null && !expectedSourceKey.isEmpty() && expectedSourceKey.size() <= 16);
            JsonNode root = JSON.readTree(value);
            require(root != null && root.isObject() && root.size() == KEYS.size());
            var names = new java.util.HashSet<String>();
            root.fieldNames().forEachRemaining(names::add);
            require(names.equals(KEYS) && PROTOCOL.equals(text(root, "protocol"))
                    && UNRESOLVED.equals(text(root, "status"))
                    && expectedSourceTable.equals(text(root, "sourceTable")));
            String snapshot = text(root, "sourceSnapshotSha256"), row = text(root, "sourceRowSha256");
            require(snapshot.matches("[a-f0-9]{64}") && row.matches("[a-f0-9]{64}"));
            JsonNode keyNode = root.get("sourceKey"), times = root.get("sourceWallTimes");
            require(keyNode.isObject() && keyNode.size() == expectedSourceKey.size()
                    && times.isObject() && times.size() <= 64);
            Map<String, Object> keys = new LinkedHashMap<>();
            for (var entry : expectedSourceKey.entrySet()) {
                require(entry.getKey() != null && entry.getKey().matches("[a-zA-Z_][a-zA-Z0-9_]{0,63}"));
                JsonNode actual = keyNode.get(entry.getKey());
                require(actual != null && !actual.isNull());
                Object expected = entry.getValue();
                if (expected instanceof String string) {
                    require(actual.isTextual() && string.equals(actual.textValue()));
                    keys.put(entry.getKey(), string);
                } else if (expected instanceof Byte || expected instanceof Short || expected instanceof Integer
                        || expected instanceof Long || expected instanceof BigInteger) {
                    require(actual.isIntegralNumber() && new BigInteger(expected.toString()).equals(actual.bigIntegerValue()));
                    keys.put(entry.getKey(), actual.bigIntegerValue());
                } else {
                    throw invalid();
                }
            }
            Map<String, String> wallTimes = new LinkedHashMap<>();
            var fields = times.fields();
            while (fields.hasNext()) {
                var field = fields.next();
                require(field.getKey().matches("[a-zA-Z_][a-zA-Z0-9_]{0,63}"));
                if (field.getValue().isNull()) {
                    wallTimes.put(field.getKey(), null);
                } else {
                    require(field.getValue().isTextual());
                    String wall = field.getValue().textValue();
                    require(wall.matches("[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}(?:\\.[0-9]{1,6})?"));
                    LocalDateTime.parse(wall, WALL_TIME);
                    wallTimes.put(field.getKey(), wall);
                }
            }
            return new LegacyClockEvidence(expectedSourceTable, keys, snapshot, row, wallTimes);
        } catch (Exception error) {
            // Never include raw JSON, caller data, account identifiers or parser excerpts in errors.
            throw invalid();
        }
    }

    public void requireWallTime(String column, String expectedRaw) {
        require(sourceWallTimes.containsKey(column) && java.util.Objects.equals(sourceWallTimes.get(column), expectedRaw));
    }

    public String protocol() { return PROTOCOL; }
    public String status() { return UNRESOLVED; }
    public String clockStatus() { return UNRESOLVED; }
    public String sourceTable() { return sourceTable; }
    public Map<String, Object> sourceKey() { return sourceKey; }
    public String sourceSnapshotSha256() { return sourceSnapshotSha256; }
    public String sourceRowSha256() { return sourceRowSha256; }
    public Map<String, String> sourceWallTimes() { return sourceWallTimes; }

    private static String text(JsonNode root, String name) {
        JsonNode node = root.get(name);
        require(node != null && node.isTextual());
        return node.textValue();
    }
    private static void require(boolean condition) { if (!condition) throw invalid(); }
    private static IllegalStateException invalid() { return new IllegalStateException("Invalid or mismatched legacy clock evidence"); }
}
