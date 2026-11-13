package com.ruanzhu.doorhandle.module.app.service;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermission;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

/** Private, externally SHA-pinned import catalogue. No documents or vectors are stored here. */
final class RagPreservationManifest {
    static final int MAX_BYTES = 2 * 1024 * 1024;
    static final int MAX_RECORDS = 1000;
    private static final Set<String> FIELDS = Set.of("version", "kind", "status", "applicationCommit", "tenant",
            "database", "collection", "collectionId", "embeddingProtocol", "embeddingDimension", "javaSourceSha256",
            "sourceBundleSha256", "policySha256", "embeddingOutputSha256", "mergeReceiptSha256", "collectionSha256",
            "collectionDigestAlgorithm", "recordCount", "records");
    private static final Set<String> RECORD_FIELDS = Set.of("id", "documentSha256", "vectorFloat32Sha256", "metadata");
    final String collectionId;
    final int dimension;
    final Map<String, Entry> records;

    private RagPreservationManifest(String collectionId, int dimension, Map<String, Entry> records) {
        this.collectionId = collectionId; this.dimension = dimension; this.records = Map.copyOf(records);
    }

    /** Shared pinned/private file reader for old-source and new-target proof protocols. */
    static byte[] privateBytes(ChatAssistantProperties properties, int maximum) throws Exception {
        require(properties.getRagPreservationManifestSha256() != null
                && properties.getRagPreservationManifestSha256().matches("[a-f0-9]{64}"), "Pinned import manifest digest required");
        require(properties.getRagPreservationCommit() != null && properties.getRagPreservationCommit().matches("[a-f0-9]{40}"),
                "Fixed import application commit required");
        Path path = Path.of(properties.getRagPreservationManifest());
        require(path.isAbsolute() && path.normalize().equals(path) && path.toRealPath().equals(path), "Canonical private import manifest required");
        for (Path part = path; part != null; part = part.getParent())
            require(!Files.isSymbolicLink(part), "Linked import manifest paths are not admitted");
        require(Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) && Files.size(path) > 0 && Files.size(path) <= maximum
                && ((Number) Files.getAttribute(path, "unix:nlink", LinkOption.NOFOLLOW_LINKS)).longValue() == 1,
                "Bounded private import manifest required");
        Set<PosixFilePermission> permissions = Files.getPosixFilePermissions(path, LinkOption.NOFOLLOW_LINKS);
        require(permissions.contains(PosixFilePermission.OWNER_READ)
                && Set.of(PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_WRITE).containsAll(permissions),
                "Import manifest must have private owner-only permissions");
        byte[] raw;
        try (var stream = Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS)) { raw = stream.readNBytes(maximum + 1); }
        require(raw.length <= maximum && sha(raw).equals(properties.getRagPreservationManifestSha256()), "Import manifest bytes differ from pinned evidence");
        return raw;
    }

    static RagPreservationManifest load(ChatAssistantProperties properties, ObjectMapper mapper) throws Exception {
        byte[] raw = privateBytes(properties, MAX_BYTES);
        ObjectMapper strict = mapper.copy().enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION);
        JsonNode root = strict.readTree(raw);
        fields(root, FIELDS);
        require(integer(root.get("version"), 1, 1) == 1
                && "doorhandle-rag-preservation-v1".equals(text(root, "kind"))
                && "MERGED_VERIFIED".equals(text(root, "status")), "Completed import preservation protocol required");
        require(properties.getRagPreservationCommit().equals(text(root, "applicationCommit")), "Import manifest belongs to another application commit");
        require(text(root, "tenant").equals(properties.getChromaTenant()) && text(root, "database").equals(properties.getChromaDatabase())
                && text(root, "collection").equals(properties.getChromaCollection()), "Import namespace differs from configured Chroma");
        require(LocalTextEmbeddingService.PROTOCOL.equals(text(root, "embeddingProtocol")), "Unrecognized local embedding protocol");
        int dimension = integer(root.get("embeddingDimension"), 32, 8192);
        require(properties.getChromaEmbeddingDimension() != null && dimension == properties.getChromaEmbeddingDimension(),
                "Import embedding dimension differs from configured hashing");
        for (String name : Set.of("sourceBundleSha256", "policySha256", "embeddingOutputSha256", "mergeReceiptSha256",
                "javaSourceSha256", "collectionSha256"))
            require(text(root, name).matches("[a-f0-9]{64}"), "Complete source, merge and vector evidence digests required");
        // The upstream digest is bound by the externally pinned manifest bytes.
        // Java verifies the complete record catalogue below; it does not claim
        // to reproduce Python's JSON number/Unicode canonical serialization.
        require("PYTHON_CANONICAL_JSON_READ_COLLECTION_V1".equals(text(root, "collectionDigestAlgorithm")), "Unrecognized upstream collection digest protocol");
        String id = text(root, "collectionId");
        require(id.matches("[A-Za-z0-9_-]{1,180}"), "Exact existing collection identity required");
        int count = integer(root.get("recordCount"), 1, MAX_RECORDS);
        require(root.get("records").isArray() && root.get("records").size() == count, "Complete nonempty import catalogue required");
        Map<String, Entry> records = new LinkedHashMap<>();
        for (JsonNode record : root.get("records")) {
            fields(record, RECORD_FIELDS);
            String recordId = text(record, "id"), documentSha = text(record, "documentSha256"), vectorSha = text(record, "vectorFloat32Sha256");
            require(recordId.length() <= 512 && documentSha.matches("[a-f0-9]{64}") && vectorSha.matches("[a-f0-9]{64}"), "Invalid complete record evidence");
            JsonNode metadata = record.get("metadata"); validateMetadata(metadata);
            require(records.put(recordId, new Entry(documentSha, vectorSha, metadata.deepCopy())) == null, "Duplicate import record identity");
        }
        return new RagPreservationManifest(id, dimension, records);
    }

    static void validateMetadata(JsonNode metadata) {
        require(metadata != null && metadata.isObject() && metadata.size() <= 128, "Complete flat Chroma metadata required");
        for (var fields = metadata.fields(); fields.hasNext();) {
            var field = fields.next(); JsonNode value = field.getValue();
            require(!field.getKey().isBlank() && field.getKey().length() <= 256 && (value.isNull() || value.isTextual() || value.isBoolean() || value.isNumber())
                    && (!value.isFloatingPointNumber() || Double.isFinite(value.doubleValue())), "Unsupported Chroma metadata value");
        }
        text(metadata, "source"); text(metadata, "title");
        require(!metadata.has("user_id") && (!metadata.has("agent_id") || metadata.get("agent_id").isNull()
                || (metadata.get("agent_id").isTextual() && "doorhandlecatch".equals(metadata.get("agent_id").textValue()))),
                "User-owned or foreign-application records require a separate RAG ownership policy");
    }

    static String vectorSha(JsonNode vector, int dimension) {
        require(vector != null && vector.isArray() && vector.size() == dimension, "Existing vector dimension differs from local hashing");
        ByteBuffer bytes = ByteBuffer.allocate(dimension * Float.BYTES).order(ByteOrder.LITTLE_ENDIAN);
        for (JsonNode coordinate : vector) {
            require(coordinate.isNumber() && Double.isFinite(coordinate.doubleValue()) && Float.isFinite(coordinate.floatValue()), "Existing vector is not finite FLOAT32");
            bytes.putFloat(coordinate.floatValue());
        }
        return sha(bytes.array());
    }
    static String vectorSha(float[] vector) {
        ByteBuffer bytes = ByteBuffer.allocate(vector.length * Float.BYTES).order(ByteOrder.LITTLE_ENDIAN);
        for (float coordinate : vector) { require(Float.isFinite(coordinate), "Local hashing produced a nonfinite vector"); bytes.putFloat(coordinate); }
        return sha(bytes.array());
    }
    static String sha(byte[] bytes) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)); }
        catch (java.security.NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }
    static String text(JsonNode object, String key) {
        JsonNode value = object.get(key);
        require(value != null && value.isTextual() && !value.textValue().isBlank(), "Required textual preservation field missing");
        return value.textValue();
    }
    static int integer(JsonNode value, int min, int max) {
        require(value != null && value.isIntegralNumber() && value.canConvertToInt() && value.intValue() >= min && value.intValue() <= max,
                "Invalid preservation count or dimension");
        return value.intValue();
    }
    private static void fields(JsonNode value, Set<String> expected) {
        require(value != null && value.isObject(), "Preservation object required");
        Set<String> actual = new HashSet<>(); value.fieldNames().forEachRemaining(actual::add);
        require(actual.equals(expected), "Preservation field set differs from the strict protocol");
    }
    static void require(boolean condition, String message) { if (!condition) throw new IllegalArgumentException(message); }
    record Entry(String documentSha256, String vectorFloat32Sha256, JsonNode metadata) { }
}
