package com.ruanzhu.doorhandle.module.app.service;

import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import com.ruanzhu.doorhandle.module.app.service.ChromaRagStoreService.RagDocument;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.Resource;
import org.springframework.core.io.ResourceLoader;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Slf4j
@Service
@RequiredArgsConstructor
public class RagKnowledgeService {

    private final ChatAssistantProperties properties;
    private final ResourceLoader resourceLoader;
    private final ChromaRagStoreService chromaRagStoreService;
    private final DeepSeekClient deepSeekClient;

    private final List<KnowledgeChunk> chunks = new ArrayList<>();
    private final ConcurrentHashMap<String, CachedContext> contextCache = new ConcurrentHashMap<>();

    private static final Pattern LATIN_TERM = Pattern.compile("[a-zA-Z0-9_\\-/]{2,}");
    private static final Pattern CHINESE_TERM = Pattern.compile("[\\u4e00-\\u9fff]{2,}");

    @PostConstruct
    public void loadKnowledgeBase() {
        if (!Boolean.TRUE.equals(properties.getRagEnabled())) {
            log.info("智能助手 RAG 已关闭");
            return;
        }
        chunks.clear();
        contextCache.clear();
        for (String source : properties.getRagSources()) {
            loadSource(source);
        }
        boolean chromaIndexed = chromaRagStoreService.indexDocuments(toRagDocuments());
        log.info("智能助手 RAG 知识库加载完成: {} 个片段", chunks.size());
        if (Boolean.TRUE.equals(properties.getChromaEnabled())) {
            log.info("Chroma RAG 状态: {}", chromaIndexed ? "已启用" : "不可用，已回退本地检索");
        }
    }

    public String retrieveContext(String query) {
        if (!Boolean.TRUE.equals(properties.getRagEnabled()) || !StringUtils.hasText(query) || chunks.isEmpty()) {
            return "";
        }
        String cacheKey = normalizeCacheKey(query);
        CachedContext cached = contextCache.get(cacheKey);
        if (cached != null && !cached.isExpired()) {
            return cached.context();
        }
        String retrievalQuery = rewriteQuery(query);
        String chromaContext = retrieveFromChroma(query, retrievalQuery);
        if (StringUtils.hasText(chromaContext)) {
            putCache(cacheKey, chromaContext);
            return chromaContext;
        }
        String localContext = retrieveFromLocalKeywords(query, retrievalQuery);
        putCache(cacheKey, localContext);
        return localContext;
    }

    private void putCache(String cacheKey, String context) {
        int ttlSeconds = properties.getRagContextCacheTtlSeconds() == null ? 120 : properties.getRagContextCacheTtlSeconds();
        if (ttlSeconds <= 0 || !StringUtils.hasText(context)) {
            return;
        }
        int maxEntries = Math.max(8, properties.getRagContextCacheMaxEntries() == null ? 128 : properties.getRagContextCacheMaxEntries());
        if (contextCache.size() >= maxEntries) {
            evictExpiredOrOldest();
        }
        contextCache.put(cacheKey, new CachedContext(context, System.currentTimeMillis() + ttlSeconds * 1000L));
    }

    private void evictExpiredOrOldest() {
        long now = System.currentTimeMillis();
        contextCache.entrySet().removeIf(entry -> entry.getValue().expiresAt() <= now);
        if (contextCache.size() < Math.max(8, properties.getRagContextCacheMaxEntries() == null ? 128 : properties.getRagContextCacheMaxEntries())) {
            return;
        }
        contextCache.entrySet().stream()
                .min(Comparator.comparingLong(entry -> entry.getValue().expiresAt()))
                .ifPresent(entry -> contextCache.remove(entry.getKey()));
    }

    private String normalizeCacheKey(String query) {
        return query.trim().replaceAll("\\s+", " ").toLowerCase(Locale.ROOT);
    }

    private String rewriteQuery(String query) {
        if (!Boolean.TRUE.equals(properties.getRagQueryRewriteEnabled())) {
            return query;
        }
        String rewritten = deepSeekClient.rewriteRagQuery(query);
        if (StringUtils.hasText(rewritten) && !rewritten.equals(query)) {
            log.debug("RAG 查询重写: {} -> {}", query, rewritten);
            return rewritten;
        }
        return query;
    }

    private String retrieveFromChroma(String originalQuery, String retrievalQuery) {
        if (!Boolean.TRUE.equals(properties.getChromaEnabled())) {
            return "";
        }
        int topK = Math.max(1, properties.getRagTopK() == null ? 4 : properties.getRagTopK());
        int candidateK = candidateK(topK);
        int maxChars = Math.max(600, properties.getRagMaxContextChars() == null ? 2600 : properties.getRagMaxContextChars());
        List<RagDocument> documents = chromaRagStoreService.query(retrievalQuery, candidateK);
        if (documents.isEmpty()) {
            return "";
        }
        documents = rerankDocuments(originalQuery, retrievalQuery, documents, topK);
        StringBuilder sb = new StringBuilder();
        sb.append("[系统知识库检索结果: Chroma + QueryRewrite + Rerank]\n");
        if (!retrievalQuery.equals(originalQuery)) {
            sb.append("检索重写：").append(retrievalQuery).append("\n");
        }
        for (RagDocument document : documents) {
            if (sb.length() >= maxChars) {
                break;
            }
            sb.append("- 来源：").append(document.title()).append("\n");
            sb.append(document.content()).append("\n\n");
        }
        if (sb.length() > maxChars) {
            return sb.substring(0, maxChars) + "\n[知识库上下文已截断]";
        }
        return sb.toString().trim();
    }

    private String retrieveFromLocalKeywords(String originalQuery, String retrievalQuery) {
        List<String> terms = extractTerms(originalQuery + " " + retrievalQuery);
        if (terms.isEmpty()) {
            return "";
        }
        int topK = Math.max(1, properties.getRagTopK() == null ? 4 : properties.getRagTopK());
        int candidateK = candidateK(topK);
        int maxChars = Math.max(600, properties.getRagMaxContextChars() == null ? 2600 : properties.getRagMaxContextChars());

        List<ScoredChunk> matched = chunks.stream()
                .map(chunk -> new ScoredChunk(chunk, score(chunk, terms)))
                .filter(item -> item.score() > 0)
                .sorted(Comparator.comparingInt(ScoredChunk::score).reversed())
                .limit(candidateK)
                .toList();

        if (matched.isEmpty()) {
            return "";
        }

        List<RagDocument> reranked = rerankDocuments(originalQuery, retrievalQuery, matched.stream()
                .map(item -> new RagDocument(
                        stableId(item.chunk(), item.score()),
                        item.chunk().source(),
                        item.chunk().title(),
                        item.chunk().content()
                ))
                .toList(), topK);

        StringBuilder sb = new StringBuilder();
        sb.append("[系统知识库检索结果: Local + QueryRewrite + Rerank]\n");
        if (!retrievalQuery.equals(originalQuery)) {
            sb.append("检索重写：").append(retrievalQuery).append("\n");
        }
        for (RagDocument document : reranked) {
            if (sb.length() >= maxChars) {
                break;
            }
            sb.append("- 来源：").append(document.title()).append("\n");
            sb.append(document.content()).append("\n\n");
        }
        if (sb.length() > maxChars) {
            return sb.substring(0, maxChars) + "\n[知识库上下文已截断]";
        }
        return sb.toString().trim();
    }

    private List<RagDocument> rerankDocuments(String originalQuery, String retrievalQuery, List<RagDocument> documents, int topK) {
        if (!Boolean.TRUE.equals(properties.getRagRerankEnabled()) || documents.size() <= topK) {
            return documents.stream().limit(topK).toList();
        }
        List<String> candidates = documents.stream()
                .map(doc -> doc.title() + "\n" + doc.content())
                .toList();
        List<Integer> indices = deepSeekClient.rerankRagCandidates(originalQuery + "\n检索重写：" + retrievalQuery, candidates, topK);
        List<RagDocument> reranked = new ArrayList<>();
        for (Integer index : indices) {
            if (index != null && index >= 0 && index < documents.size()) {
                RagDocument document = documents.get(index);
                if (!reranked.contains(document)) {
                    reranked.add(document);
                }
                if (reranked.size() >= topK) {
                    break;
                }
            }
        }
        if (reranked.isEmpty()) {
            return documents.stream().limit(topK).toList();
        }
        for (RagDocument document : documents) {
            if (reranked.size() >= topK) {
                break;
            }
            if (!reranked.contains(document)) {
                reranked.add(document);
            }
        }
        return reranked;
    }

    private int candidateK(int topK) {
        int multiplier = Math.max(1, properties.getRagCandidateMultiplier() == null
                ? 3
                : properties.getRagCandidateMultiplier());
        return Math.max(topK, topK * multiplier);
    }

    private List<RagDocument> toRagDocuments() {
        List<RagDocument> documents = new ArrayList<>();
        for (int i = 0; i < chunks.size(); i++) {
            KnowledgeChunk chunk = chunks.get(i);
            documents.add(new RagDocument(
                    stableId(chunk, i),
                    chunk.source(),
                    chunk.title(),
                    chunk.content()
            ));
        }
        return documents;
    }

    private String stableId(KnowledgeChunk chunk, int index) {
        return Integer.toHexString((chunk.source() + "|" + chunk.title() + "|" + index).hashCode());
    }

    public int chunkCount() {
        return chunks.size();
    }

    private void loadSource(String location) {
        if (!StringUtils.hasText(location)) {
            return;
        }
        try {
            Resource resource = resourceLoader.getResource(location);
            if (!resource.exists()) {
                log.debug("RAG 知识源不存在，跳过: {}", location);
                return;
            }
            String content;
            try (InputStream inputStream = resource.getInputStream()) {
                content = new String(inputStream.readAllBytes(), StandardCharsets.UTF_8);
            }
            splitIntoChunks(location, content);
        } catch (IOException e) {
            log.warn("加载 RAG 知识源失败: {} - {}", location, e.getMessage());
        }
    }

    private void splitIntoChunks(String source, String content) {
        if (!StringUtils.hasText(content)) {
            return;
        }
        int chunkSize = Math.max(300, properties.getRagChunkSize() == null ? 900 : properties.getRagChunkSize());
        String currentTitle = source;
        StringBuilder buffer = new StringBuilder();
        for (String rawLine : content.split("\\R")) {
            String line = rawLine.strip();
            if (line.startsWith("#")) {
                flushChunk(source, currentTitle, buffer);
                currentTitle = line.replaceFirst("^#+\\s*", "");
                buffer.setLength(0);
            }
            if (!line.isBlank()) {
                buffer.append(line).append('\n');
            }
            if (buffer.length() >= chunkSize) {
                flushChunk(source, currentTitle, buffer);
                buffer.setLength(0);
            }
        }
        flushChunk(source, currentTitle, buffer);
    }

    private void flushChunk(String source, String title, StringBuilder buffer) {
        String text = buffer.toString().trim();
        if (text.length() < 20) {
            return;
        }
        chunks.add(new KnowledgeChunk(source, title, text, text.toLowerCase(Locale.ROOT)));
    }

    private int score(KnowledgeChunk chunk, List<String> terms) {
        int score = 0;
        String haystack = chunk.normalizedContent();
        String title = chunk.title().toLowerCase(Locale.ROOT);
        for (String term : terms) {
            String normalized = term.toLowerCase(Locale.ROOT);
            if (haystack.contains(normalized)) {
                score += 2;
            }
            if (title.contains(normalized)) {
                score += 4;
            }
        }
        return score;
    }

    private List<String> extractTerms(String query) {
        Set<String> terms = new LinkedHashSet<>();
        String normalized = query.toLowerCase(Locale.ROOT);
        Matcher latinMatcher = LATIN_TERM.matcher(normalized);
        while (latinMatcher.find()) {
            terms.add(latinMatcher.group());
        }
        Matcher chineseMatcher = CHINESE_TERM.matcher(query);
        while (chineseMatcher.find()) {
            String token = chineseMatcher.group();
            terms.add(token);
            for (int i = 0; i < token.length() - 1; i++) {
                terms.add(token.substring(i, i + 2));
            }
            for (int i = 0; i < token.length() - 3; i++) {
                terms.add(token.substring(i, i + 4));
            }
        }
        return terms.stream()
                .filter(term -> term.length() >= 2)
                .limit(80)
                .toList();
    }

    private record KnowledgeChunk(String source, String title, String content, String normalizedContent) {
    }

    private record ScoredChunk(KnowledgeChunk chunk, int score) {
    }

    private record CachedContext(String context, long expiresAt) {
        boolean isExpired() {
            return expiresAt <= System.currentTimeMillis();
        }
    }
}
