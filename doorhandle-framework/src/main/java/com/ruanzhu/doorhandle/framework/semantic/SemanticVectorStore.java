package com.ruanzhu.doorhandle.framework.semantic;

import java.util.List;
import java.util.Map;

/** Generic derived index. Callers must supply both prefilters and authoritative post-read checks. */
public interface SemanticVectorStore {
    record Document(String id, String text, Map<String,String> metadata) {
        public Document { metadata=Map.copyOf(metadata); }
    }
    record Hit(String id, double score, String text, Map<String,String> metadata) { }
    record Filter(Map<String,String> all, List<Map<String,String>> any) {
        public Filter { all=Map.copyOf(all); any=any.stream().map(Map::copyOf).toList(); }
        public static Filter all(Map<String,String> fields) { return new Filter(fields,List.of()); }
    }
    void upsert(String collection, List<Document> documents, EmbeddingClient.RequestContext context);
    List<Hit> search(String collection, String query, Filter filter, int limit, EmbeddingClient.RequestContext context);
    /** Attaches an admitted, already populated collection without requesting embeddings or modifying points. */
    void verifyCollection(String collection);
    /** Exact current text/metadata readback; never infers readiness from SQL chunk state. */
    boolean contains(String collection, List<Document> documents);
    /** Exact normalized float32 little-endian fingerprints for restart/independent-restore evidence. */
    Map<String,String> storedFingerprints(String collection,List<Document> documents);
    long count(String collection,Filter filter);
}
