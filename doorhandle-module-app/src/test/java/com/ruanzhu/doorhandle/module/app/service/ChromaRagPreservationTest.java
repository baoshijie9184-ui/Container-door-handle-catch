package com.ruanzhu.doorhandle.module.app.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.core.io.ResourceLoader;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Actual loopback HTTP and private-file checks, executed only by the ECS source suite. */
class ChromaRagPreservationTest {
    private static final String COLLECTION = "door_handle_assistant_knowledge", COLLECTION_ID = "existing-collection";
    @TempDir Path directory;
    private final ObjectMapper json = new ObjectMapper();
    private final List<String> ids = new ArrayList<>(), documents = new ArrayList<>();
    private final List<Map<String, Object>> metadata = new ArrayList<>();
    private final List<List<Float>> vectors = new ArrayList<>();
    private final AtomicInteger writes = new AtomicInteger(), queries = new AtomicInteger(), gets = new AtomicInteger();
    private HttpServer server;
    private ChatAssistantProperties properties;
    private LocalTextEmbeddingService embedding;
    private boolean missing, wrongMember, corruptVector;
    private int serverDimension = 32;

    @BeforeEach void setup() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", this::handle); server.start();
        properties = new ChatAssistantProperties();
        properties.setChromaEnabled(true); // Explicit legacy-source regression, never a runtime fallback.
        properties.setRagStartupMode(ChatAssistantProperties.RagStartupMode.PRESERVE_EXISTING);
        properties.setChromaBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
        properties.setChromaEmbeddingDimension(32);
        properties.setRagQueryRewriteEnabled(false); properties.setRagRerankEnabled(false);
        properties.setRagPreservationCommit("b".repeat(40));
        embedding = new LocalTextEmbeddingService(properties);
        for (int i = 0; i < 83; i++) {
            String text = "服务器保留资料 original-" + i + " 说明集装箱检测及资料检索的历史内容";
            ids.add("legacy-" + i); documents.add(text);
            metadata.add(Map.of("source", "file:README.md", "title", "已导入资料 " + i, "version", 1, "enabled", true));
            List<Float> vector = new ArrayList<>(); for (float value : embedding.embed(text)) vector.add(value); vectors.add(vector);
        }
        writeManifest(manifest());
    }
    @AfterEach void close() { if (server != null) server.stop(0); }

    @Test void preservesAll83RecordsAndRetrievesRemotelyWithNoLocalChunksOrWrites() {
        ChromaRagStoreService store = store();
        ResourceLoader resources = mock(ResourceLoader.class);
        RagKnowledgeService knowledge = new RagKnowledgeService(properties, resources, store, mock(RagModelService.class));
        knowledge.loadKnowledgeBase();
        assertThat(knowledge.chunkCount()).isZero();
        String context = knowledge.retrieveContext(documents.get(82));
        assertThat(context).contains("Chroma", "服务器保留资料");
        assertThat(store.isAvailable()).isTrue();
        assertThat(queries.get()).isEqualTo(2); // a real startup self-query and the user's real retrieval
        assertThat(gets.get()).isEqualTo(1);
        assertThat(ids).hasSize(83); assertThat(writes.get()).isZero();
        verifyNoInteractions(resources);
    }

    @Test void preservationRejectsExplicitReindexEvenForAnEmptyDocumentList() {
        ChromaRagStoreService store = store();
        assertThatThrownBy(() -> store.indexDocuments(List.of())).isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(() -> store.indexDocuments(List.of(new ChromaRagStoreService.RagDocument("new", "file:README.md", "new", "new text"))))
                .isInstanceOf(IllegalStateException.class);
        assertThat(writes.get()).isZero(); assertThat(gets.get()).isZero();
    }

    @Test void missingExistingCollectionFailsWithoutCreatingOne() {
        missing = true; assertRejected(); assertThat(writes.get()).isZero();
    }

    @Test void wrongDimensionFailsWithoutReplacingTheCollection() {
        serverDimension = 64; assertRejected(); assertThat(writes.get()).isZero();
    }

    @Test void alteredStoredVectorFailsAgainstThePrivateCatalogue() {
        corruptVector = true; assertRejected(); assertThat(writes.get()).isZero();
    }

    @Test void matchingManifestAndDimensionLabelCannotDisguiseAnotherEmbeddingAlgorithm() throws Exception {
        vectors.set(0, new ArrayList<>(java.util.Collections.nCopies(32, 0.0f)));
        writeManifest(manifest());
        assertRejected(); assertThat(writes.get()).isZero();
    }

    @Test void substitutedMembershipFailsEvenWhenCountIsUnchanged() {
        wrongMember = true; assertRejected(); assertThat(writes.get()).isZero();
    }

    @Test void modifiedManifestBytesFailBeforeAnyCollectionRead() throws Exception {
        Files.writeString(Path.of(properties.getRagPreservationManifest()), "\n", java.nio.file.StandardOpenOption.APPEND);
        assertRejected(); assertThat(gets.get()).isZero();
    }

    @Test void missingSourceOrMergeEvidenceCannotBeReplacedByAStartupBoolean() throws Exception {
        Map<String, Object> manifest = manifest(); manifest.remove("mergeReceiptSha256"); manifest.put("applicationReindexComplete", true);
        writeManifest(manifest); assertRejected(); assertThat(gets.get()).isZero();
    }

    @Test void anotherCommitOrProtocolIsRefusedDespiteValidRawManifestChecksum() throws Exception {
        Map<String, Object> manifest = manifest(); manifest.put("applicationCommit", "c".repeat(40));
        writeManifest(manifest); assertRejected();
        manifest = manifest(); manifest.put("embeddingProtocol", "another-provider-32");
        writeManifest(manifest); assertRejected(); assertThat(writes.get()).isZero();
    }

    @Test void publicOrLinkedImportManifestsFailClosed() throws Exception {
        Path original = Path.of(properties.getRagPreservationManifest());
        Files.setPosixFilePermissions(original, PosixFilePermissions.fromString("rw-r--r--")); assertRejected();
        Files.setPosixFilePermissions(original, PosixFilePermissions.fromString("rw-------"));
        Path link = directory.resolve("linked.json"); Files.createSymbolicLink(link, original);
        properties.setRagPreservationManifest(link.toString()); assertRejected();
        properties.setRagPreservationManifest(original.toString());
        Files.createLink(directory.resolve("hard-link.json"), original); assertRejected();
        assertThat(writes.get()).isZero();
    }

    @Test void preservedStartupCannotSilentlyFallBackWhenRemoteRagIsDisabled() {
        properties.setChromaEnabled(false); assertRejected();
    }

    private ChromaRagStoreService store() { return new ChromaRagStoreService(properties, embedding, json); }
    private void assertRejected() {
        ChromaRagStoreService store = store();
        assertThatThrownBy(store::attachPreservedCollection).isInstanceOf(IllegalStateException.class)
                .hasMessage("RAG preservation validation failed; existing collection was not modified");
        assertThat(store.isAvailable()).isFalse();
    }

    private Map<String, Object> manifest() throws Exception {
        Map<String, Object> value = new LinkedHashMap<>();
        value.put("version", 1); value.put("kind", "doorhandle-rag-preservation-v1"); value.put("status", "MERGED_VERIFIED");
        value.put("applicationCommit", properties.getRagPreservationCommit()); value.put("tenant", properties.getChromaTenant());
        value.put("database", properties.getChromaDatabase()); value.put("collection", COLLECTION); value.put("collectionId", COLLECTION_ID);
        value.put("embeddingProtocol", LocalTextEmbeddingService.PROTOCOL); value.put("embeddingDimension", 32);
        for (String key : List.of("javaSourceSha256", "sourceBundleSha256", "policySha256", "embeddingOutputSha256", "mergeReceiptSha256", "collectionSha256"))
            value.put(key, "a".repeat(64));
        value.put("collectionDigestAlgorithm", "PYTHON_CANONICAL_JSON_READ_COLLECTION_V1"); value.put("recordCount", ids.size());
        List<Map<String, Object>> rows = new ArrayList<>();
        for (int i = 0; i < ids.size(); i++) rows.add(Map.of("id", ids.get(i), "documentSha256", RagPreservationManifest.sha(documents.get(i).getBytes(StandardCharsets.UTF_8)),
                "vectorFloat32Sha256", RagPreservationManifest.vectorSha(json.valueToTree(vectors.get(i)), 32), "metadata", metadata.get(i)));
        value.put("records", rows); return value;
    }
    private void writeManifest(Map<String, Object> value) throws Exception {
        Path file = directory.resolve("preservation.json").toAbsolutePath(); byte[] raw = json.writeValueAsBytes(value);
        Files.write(file, raw); Files.setPosixFilePermissions(file, PosixFilePermissions.fromString("rw-------"));
        properties.setRagPreservationManifest(file.toString()); properties.setRagPreservationManifestSha256(RagPreservationManifest.sha(raw));
    }

    private void handle(HttpExchange exchange) throws IOException {
        try {
            String path = exchange.getRequestURI().getPath(), method = exchange.getRequestMethod();
            if (path.endsWith("/collections") || path.endsWith("/delete") || path.endsWith("/upsert") || path.endsWith("/add")) {
                writes.incrementAndGet(); respond(exchange, 409, Map.of("error", "writes forbidden")); return;
            }
            if (path.endsWith("/collections/" + COLLECTION) && "GET".equals(method)) {
                if (missing) respond(exchange, 404, Map.of("error", "missing"));
                else respond(exchange, 200, Map.of("id", COLLECTION_ID, "name", COLLECTION, "dimension", serverDimension,
                        "metadata", Map.of("embedding", "local-hashing-" + serverDimension)));
            } else if (path.endsWith("/" + COLLECTION_ID + "/count")) respond(exchange, 200, ids.size());
            else if (path.endsWith("/" + COLLECTION_ID + "/get")) {
                gets.incrementAndGet(); List<String> returnedIds = new ArrayList<>(ids);
                if (wrongMember) returnedIds.set(returnedIds.size() - 1, "unexpected-record");
                List<List<Float>> returnedVectors = new ArrayList<>(vectors);
                if (corruptVector) returnedVectors.set(0, java.util.Collections.nCopies(32, 1.0f));
                respond(exchange, 200, Map.of("ids", returnedIds, "documents", documents, "metadatas", metadata, "embeddings", returnedVectors));
            } else if (path.endsWith("/" + COLLECTION_ID + "/query")) {
                queries.incrementAndGet(); JsonNode request = json.readTree(exchange.getRequestBody());
                String requested = RagPreservationManifest.vectorSha(request.path("query_embeddings").path(0), 32); int chosen = 0;
                for (int i = 0; i < vectors.size(); i++) if (RagPreservationManifest.vectorSha(json.valueToTree(vectors.get(i)), 32).equals(requested)) { chosen = i; break; }
                respond(exchange, 200, Map.of("ids", List.of(List.of(ids.get(chosen))), "documents", List.of(List.of(documents.get(chosen))),
                        "metadatas", List.of(List.of(metadata.get(chosen))), "distances", List.of(List.of(0.0))));
            } else respond(exchange, 404, Map.of("error", "unsupported"));
        } catch (Exception failure) { respond(exchange, 500, Map.of("error", "private fixture read failed")); }
    }
    private void respond(HttpExchange exchange, int status, Object value) throws IOException {
        byte[] raw = json.writeValueAsBytes(value); exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, raw.length); exchange.getResponseBody().write(raw); exchange.close();
    }
}
