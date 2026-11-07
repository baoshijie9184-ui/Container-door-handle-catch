package com.ruanzhu.doorhandle.module.app.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestTemplate;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicBoolean;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;

@Slf4j
@Service
@RequiredArgsConstructor
public class ChromaRagStoreService {

    private final ChatAssistantProperties properties;
    private final LocalTextEmbeddingService embeddingService;
    private final ObjectMapper objectMapper;

    private final AtomicBoolean available = new AtomicBoolean(false);
    private volatile String collectionId;
    private volatile RagPreservationManifest preservation;
    private static final int MAX_PRESERVATION_RESPONSE_BYTES = 32 * 1024 * 1024;

    public boolean indexDocuments(List<RagDocument> documents) {
        if (preserveExisting()) throw new IllegalStateException("Preserved RAG collections cannot be reindexed");
        if (!Boolean.TRUE.equals(properties.getChromaEnabled()) || documents == null || documents.isEmpty()) {
            return false;
        }
        try {
            ensureCollection();
            deleteExistingSources(documents);
            upsertDocuments(documents);
            available.set(true);
            log.info("Chroma RAG 索引完成: collection={} docs={}", collectionId, documents.size());
            return true;
        } catch (Exception e) {
            available.set(false);
            log.warn("Chroma RAG 索引失败，将使用本地检索兜底: {}", e.getMessage());
            return false;
        }
    }

    public List<RagDocument> query(String query, int topK) {
        if (!Boolean.TRUE.equals(properties.getChromaEnabled()) || !available.get() || !StringUtils.hasText(collectionId)) {
            return List.of();
        }
        try {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("query_embeddings", List.of(toDoubleList(embeddingService.embed(query))));
            int requested = Math.max(1, topK);
            body.put("n_results", preserveExisting() && preservation != null ? Math.min(requested, preservation.records.size()) : requested);
            body.put("include", List.of("documents", "metadatas", "distances"));

            List<RagDocument> results;
            if (preserveExisting()) results = parseQueryResponse(readExisting(collectionUrl() + "/" + collectionId + "/query", body));
            else {
                ResponseEntity<String> response = restTemplate().exchange(collectionUrl() + "/" + collectionId + "/query",
                        HttpMethod.POST, new HttpEntity<>(body, headers()), String.class);
                results = parseQueryResponse(response.getBody());
            }
            available.set(true);
            return results;
        } catch (Exception e) {
            if (preserveExisting()) log.warn("Preserved Chroma RAG query failed validation or availability; no index writes performed");
            else log.warn("Chroma RAG 查询失败，本次回退本地检索，后续请求将继续尝试 Chroma: {}", e.getMessage());
            return List.of();
        }
    }

    public boolean isAvailable() {
        return available.get();
    }

    /** Read and verify an existing imported index; no create, delete or upsert is admitted. */
    public synchronized void attachPreservedCollection() {
        available.set(false); collectionId = null; preservation = null;
        try {
            RagPreservationManifest.require(preserveExisting() && Boolean.TRUE.equals(properties.getRagEnabled())
                    && Boolean.TRUE.equals(properties.getChromaEnabled()), "Preservation requires explicitly enabled remote RAG");
            validatePreservationEndpoint();
            RagPreservationManifest manifest = RagPreservationManifest.load(properties, objectMapper);
            JsonNode collection = readExisting(collectionUrl() + "/" + properties.getChromaCollection(), null);
            RagPreservationManifest.require(manifest.collectionId.equals(RagPreservationManifest.text(collection, "id"))
                    && properties.getChromaCollection().equals(RagPreservationManifest.text(collection, "name"))
                    && ("local-hashing-" + manifest.dimension).equals(collection.path("metadata").path("embedding").asText()),
                    "Existing collection identity or embedding label differs from import evidence");
            if (collection.has("dimension"))
                RagPreservationManifest.require(RagPreservationManifest.integer(collection.get("dimension"), 32, 8192) == manifest.dimension,
                        "Existing collection reports a different vector dimension");
            String endpoint = collectionUrl() + "/" + manifest.collectionId;
            verifyCount(endpoint, manifest.records.size());
            JsonNode rows = readExisting(endpoint + "/get", Map.of("offset", 0, "limit", manifest.records.size() + 1,
                    "include", List.of("documents", "metadatas", "embeddings")));
            for (String field : List.of("ids", "documents", "metadatas", "embeddings"))
                RagPreservationManifest.require(rows.path(field).isArray() && rows.path(field).size() == manifest.records.size(),
                        "Existing collection does not contain the complete imported catalogue");
            Set<String> found = new LinkedHashSet<>(); String probeId = null; float[] probe = null;
            for (int i = 0; i < rows.path("ids").size(); i++) {
                RagPreservationManifest.require(rows.path("ids").get(i).isTextual(), "Existing record identity is missing");
                String id = rows.path("ids").get(i).textValue();
                RagPreservationManifest.Entry expected = manifest.records.get(id);
                RagPreservationManifest.require(expected != null && found.add(id), "Existing collection gained or duplicated record identities");
                JsonNode document = rows.path("documents").get(i), metadata = rows.path("metadatas").get(i);
                RagPreservationManifest.require(document.isTextual() && StringUtils.hasText(document.textValue())
                        && expected.documentSha256().equals(RagPreservationManifest.sha(document.textValue().getBytes(StandardCharsets.UTF_8)))
                        && expected.metadata().equals(metadata), "Existing document or metadata differs from imported evidence");
                String actual = RagPreservationManifest.vectorSha(rows.path("embeddings").get(i), manifest.dimension);
                float[] local = embeddingService.embed(document.textValue());
                RagPreservationManifest.require(local.length == manifest.dimension && expected.vectorFloat32Sha256().equals(actual)
                        && expected.vectorFloat32Sha256().equals(RagPreservationManifest.vectorSha(local)),
                        "Existing vectors do not implement the pinned local hashing protocol");
                if (probe == null) { probe = local; probeId = id; }
            }
            RagPreservationManifest.require(found.equals(manifest.records.keySet()), "Imported catalogue membership changed");
            verifyCount(endpoint, manifest.records.size());
            JsonNode selfLookup = readExisting(endpoint + "/query", Map.of("query_embeddings", List.of(toDoubleList(probe)),
                    "n_results", manifest.records.size(), "include", List.of("distances")));
            JsonNode ids = selfLookup.path("ids").path(0), distances = selfLookup.path("distances").path(0);
            boolean foundSelf = false;
            for (int i = 0; ids.isArray() && i < ids.size(); i++)
                if (probeId.equals(ids.get(i).asText()) && distances.path(i).isNumber()
                        && Double.isFinite(distances.path(i).doubleValue()) && Math.abs(distances.path(i).doubleValue()) <= 0.0001)
                    foundSelf = true;
            RagPreservationManifest.require(foundSelf, "Existing vector index cannot retrieve its verified document");
            collectionId = manifest.collectionId; preservation = manifest; available.set(true);
            log.info("Chroma RAG preserved collection attached: verifiedRecords={} protocol={}", found.size(), LocalTextEmbeddingService.PROTOCOL);
        } catch (Exception rejected) {
            collectionId = null; preservation = null; available.set(false);
            // Chroma response bodies and the private evidence never enter a
            // startup exception or a log, including parser/HTTP failure cases.
            throw new IllegalStateException("RAG preservation validation failed; existing collection was not modified");
        }
    }

    private boolean preserveExisting() {
        if (properties.getRagStartupMode() == null) throw new IllegalStateException("Explicit RAG startup mode required");
        return properties.getRagStartupMode() == ChatAssistantProperties.RagStartupMode.PRESERVE_EXISTING;
    }

    private void validatePreservationEndpoint() throws Exception {
        URI uri = URI.create(trimTrailingSlash(properties.getChromaBaseUrl()));
        RagPreservationManifest.require(Set.of("http", "https").contains(uri.getScheme()) && uri.getHost() != null
                && uri.getUserInfo() == null && uri.getRawQuery() == null && uri.getRawFragment() == null
                && (uri.getRawPath() == null || uri.getRawPath().isEmpty()) && uri.getPort() != 0,
                "Private Chroma base endpoint required");
        for (InetAddress address : InetAddress.getAllByName(uri.getHost()))
            RagPreservationManifest.require(address.isLoopbackAddress() || address.isSiteLocalAddress() || address.isLinkLocalAddress(),
                    "Preservation endpoint must remain on a private interface");
        for (String name : List.of(properties.getChromaTenant(), properties.getChromaDatabase(), properties.getChromaCollection()))
            RagPreservationManifest.require(name != null && name.matches("[A-Za-z0-9_-]{1,180}"), "Safe exact Chroma namespace required");
    }

    private void verifyCount(String endpoint, int expected) throws Exception {
        RagPreservationManifest.require(RagPreservationManifest.integer(readExisting(endpoint + "/count", null), 1,
                RagPreservationManifest.MAX_RECORDS) == expected, "Existing collection count differs from complete import evidence");
    }

    private JsonNode readExisting(String url, Map<String, Object> body) {
        RestTemplate client = restTemplate();
        client.setErrorHandler(new org.springframework.web.client.ResponseErrorHandler() {
            @Override public boolean hasError(org.springframework.http.client.ClientHttpResponse response) { return false; }
            @Override public void handleError(org.springframework.http.client.ClientHttpResponse response) { }
        });
        return client.execute(url, body == null ? HttpMethod.GET : HttpMethod.POST,
                request -> { request.getHeaders().putAll(headers()); if (body != null) request.getBody().write(objectMapper.writeValueAsBytes(body)); },
                response -> {
                    if (response.getStatusCode().value() != 200) throw new IOException("Existing Chroma read failed");
                    byte[] raw = response.getBody().readNBytes(MAX_PRESERVATION_RESPONSE_BYTES + 1);
                    if (raw.length == 0 || raw.length > MAX_PRESERVATION_RESPONSE_BYTES) throw new IOException("Existing Chroma read exceeded its bound");
                    return objectMapper.copy().enable(com.fasterxml.jackson.core.JsonParser.Feature.STRICT_DUPLICATE_DETECTION).readTree(raw);
                });
    }

    private void ensureCollection() throws Exception {
        if (StringUtils.hasText(collectionId)) {
            return;
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("name", properties.getChromaCollection());
        body.put("get_or_create", true);
        body.put("metadata", Map.of(
                "description", "DoorHandleCatch assistant RAG knowledge base",
                "embedding", "local-hashing-" + properties.getChromaEmbeddingDimension()
        ));
        ResponseEntity<String> response = restTemplate().exchange(
                collectionUrl(),
                HttpMethod.POST,
                new HttpEntity<>(body, headers()),
                String.class
        );
        JsonNode root = objectMapper.readTree(response.getBody());
        collectionId = root.path("id").asText(properties.getChromaCollection());
    }

    private void deleteExistingSources(List<RagDocument> documents) {
        Set<String> sources = new LinkedHashSet<>();
        for (RagDocument document : documents) {
            if (StringUtils.hasText(document.source())) {
                sources.add(document.source());
            }
        }
        if (sources.isEmpty()) {
            return;
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("where", Map.of("source", Map.of("$in", new ArrayList<>(sources))));
        try {
            restTemplate().exchange(
                    collectionUrl() + "/" + collectionId + "/delete",
                    HttpMethod.POST,
                    new HttpEntity<>(body, headers()),
                    String.class
            );
        } catch (Exception e) {
            log.warn("清理 Chroma 旧知识片段失败，将继续 upsert 当前片段: {}", e.getMessage());
        }
    }

    private void upsertDocuments(List<RagDocument> documents) {
        List<String> ids = new ArrayList<>();
        List<List<Double>> embeddings = new ArrayList<>();
        List<String> contents = new ArrayList<>();
        List<Map<String, Object>> metadatas = new ArrayList<>();

        for (RagDocument document : documents) {
            ids.add(document.id());
            embeddings.add(toDoubleList(embeddingService.embed(document.content())));
            contents.add(document.content());
            metadatas.add(Map.of(
                    "source", document.source(),
                    "title", document.title()
            ));
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("ids", ids);
        body.put("embeddings", embeddings);
        body.put("documents", contents);
        body.put("metadatas", metadatas);

        restTemplate().exchange(
                collectionUrl() + "/" + collectionId + "/upsert",
                HttpMethod.POST,
                new HttpEntity<>(body, headers()),
                String.class
        );
    }

    private List<RagDocument> parseQueryResponse(String body) throws Exception {
        if (!StringUtils.hasText(body)) {
            return List.of();
        }
        JsonNode root = objectMapper.readTree(body);
        return parseQueryResponse(root);
    }

    private List<RagDocument> parseQueryResponse(JsonNode root) {
        JsonNode documentsNode = root.path("documents").path(0);
        JsonNode metadatasNode = root.path("metadatas").path(0);
        JsonNode idsNode = root.path("ids").path(0);
        if (preserveExisting())
            RagPreservationManifest.require(idsNode.isArray() && documentsNode.isArray() && metadatasNode.isArray()
                    && idsNode.size() == documentsNode.size() && idsNode.size() == metadatasNode.size(),
                    "Preserved query must identify every returned catalogue record");
        List<RagDocument> results = new ArrayList<>();
        if (!documentsNode.isArray()) {
            return results;
        }
        for (int i = 0; i < documentsNode.size(); i++) {
            if (preserveExisting())
                RagPreservationManifest.require(documentsNode.get(i).isTextual() && StringUtils.hasText(documentsNode.get(i).textValue())
                        && idsNode.get(i).isTextual(), "Preserved query returned a malformed catalogue record");
            String content = documentsNode.get(i).asText("");
            JsonNode metadata = metadatasNode.path(i);
            String source = metadata.path("source").asText("Chroma");
            String title = metadata.path("title").asText(source);
            if (StringUtils.hasText(content)) {
                String id = idsNode.path(i).asText("chroma-" + i);
                if (preserveExisting()) {
                    RagPreservationManifest.Entry expected = preservation == null ? null : preservation.records.get(id);
                    RagPreservationManifest.require(expected != null && expected.metadata().equals(metadata)
                            && expected.documentSha256().equals(RagPreservationManifest.sha(content.getBytes(StandardCharsets.UTF_8))),
                            "Query result differs from attached preservation catalogue");
                }
                results.add(new RagDocument(id, source, title, content));
            }
        }
        return results;
    }

    private HttpHeaders headers() {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        if (StringUtils.hasText(properties.getChromaToken())) {
            headers.set("x-chroma-token", properties.getChromaToken());
        }
        return headers;
    }

    private RestTemplate restTemplate() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory() {
            @Override protected void prepareConnection(HttpURLConnection connection, String method) throws IOException {
                super.prepareConnection(connection, method); connection.setInstanceFollowRedirects(false);
            }
        };
        int connectTimeout = properties.getChromaConnectTimeoutMs() == null ? 1000 : properties.getChromaConnectTimeoutMs();
        int readTimeout = properties.getChromaReadTimeoutMs() == null ? 3000 : properties.getChromaReadTimeoutMs();
        factory.setConnectTimeout(Math.max(200, connectTimeout));
        factory.setReadTimeout(Math.max(500, readTimeout));
        return new RestTemplate(factory);
    }

    private String collectionUrl() {
        return trimTrailingSlash(properties.getChromaBaseUrl())
                + "/api/v2/tenants/" + properties.getChromaTenant()
                + "/databases/" + properties.getChromaDatabase()
                + "/collections";
    }

    private String trimTrailingSlash(String value) {
        String text = StringUtils.hasText(value) ? value : "http://localhost:8000";
        while (text.endsWith("/")) {
            text = text.substring(0, text.length() - 1);
        }
        return text;
    }

    private List<Double> toDoubleList(float[] vector) {
        List<Double> values = new ArrayList<>(vector.length);
        for (float value : vector) {
            values.add((double) value);
        }
        return values;
    }

    public record RagDocument(String id, String source, String title, String content) {
    }
}
