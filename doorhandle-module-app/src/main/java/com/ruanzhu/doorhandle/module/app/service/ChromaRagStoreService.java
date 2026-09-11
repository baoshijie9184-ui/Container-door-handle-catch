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

@Slf4j
@Service
@RequiredArgsConstructor
public class ChromaRagStoreService {

    private final ChatAssistantProperties properties;
    private final LocalTextEmbeddingService embeddingService;
    private final ObjectMapper objectMapper;

    private final AtomicBoolean available = new AtomicBoolean(false);
    private volatile String collectionId;

    public boolean indexDocuments(List<RagDocument> documents) {
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
            body.put("n_results", Math.max(1, topK));
            body.put("include", List.of("documents", "metadatas", "distances"));

            ResponseEntity<String> response = restTemplate().exchange(
                    collectionUrl() + "/" + collectionId + "/query",
                    HttpMethod.POST,
                    new HttpEntity<>(body, headers()),
                    String.class
            );
            List<RagDocument> results = parseQueryResponse(response.getBody());
            available.set(true);
            return results;
        } catch (Exception e) {
            log.warn("Chroma RAG 查询失败，本次回退本地检索，后续请求将继续尝试 Chroma: {}", e.getMessage());
            return List.of();
        }
    }

    public boolean isAvailable() {
        return available.get();
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
        JsonNode documentsNode = root.path("documents").path(0);
        JsonNode metadatasNode = root.path("metadatas").path(0);
        List<RagDocument> results = new ArrayList<>();
        if (!documentsNode.isArray()) {
            return results;
        }
        for (int i = 0; i < documentsNode.size(); i++) {
            String content = documentsNode.get(i).asText("");
            JsonNode metadata = metadatasNode.path(i);
            String source = metadata.path("source").asText("Chroma");
            String title = metadata.path("title").asText(source);
            if (StringUtils.hasText(content)) {
                results.add(new RagDocument("chroma-" + i, source, title, content));
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
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
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
