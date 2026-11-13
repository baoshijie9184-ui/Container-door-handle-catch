package com.ruanzhu.doorhandle.module.app.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.semantic.*;
import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import com.ruanzhu.doorhandle.module.app.service.ChromaRagStoreService.RagDocument;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;

/** System/public knowledge only. Managed user knowledge has its own collection and SQL access checks. */
@Service
public final class QdrantRagStoreService {
    private final SemanticVectorStore store;
    private final SemanticProperties semantic;
    private final ChatAssistantProperties properties;
    private final ObjectMapper json;
    private volatile String generation;
    private volatile String state="NOT_CHECKED";
    public QdrantRagStoreService(SemanticVectorStore store,SemanticProperties semantic,ChatAssistantProperties properties,ObjectMapper json) {
        this.store=store;this.semantic=semantic;this.properties=properties;this.json=json;
    }
    public boolean enabled(){return semantic.isEnabled();}
    public String state(){return state;}
    private static String digest(String text) {
        try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8)));}
        catch(java.security.NoSuchAlgorithmException unavailable){throw new IllegalStateException(unavailable);}
    }
    public boolean indexDocuments(List<RagDocument> documents) {
        if(properties.getRagStartupMode()!=ChatAssistantProperties.RagStartupMode.REINDEX)throw new IllegalStateException("Explicit system index rebuild required");
        if(!enabled()||documents.isEmpty())return false;
        String next=digest(documents.stream().map(doc->doc.id()+"\0"+doc.source()+"\0"+doc.title()+"\0"+doc.content()).reduce("",(a,b)->a+"\n"+b));
        var records=new ArrayList<SemanticVectorStore.Document>();
        for(var doc:documents){var parts=SemanticDocuments.split(doc.content());for(int i=0;i<parts.size();i++)records.add(new SemanticVectorStore.Document(
                doc.id()+"@"+next+":"+i,parts.get(i),Map.of("kind","SYSTEM_RAG","source_id",doc.id(),"source",doc.source(),"title",doc.title(),"version",next,"generation",next,"lifecycle","ACTIVE","visibility","SYSTEM")));}
        try {
            // Exact current point readback avoids rebilling unchanged documents after a normal restart.
            boolean current=false;try{current=store.contains(semantic.getRagCollection(),records);}catch(SemanticUnavailableException absent){/* First admitted index. */}
            if(!current)store.upsert(semantic.getRagCollection(),records,new EmbeddingClient.RequestContext("SYSTEM_RAG","doorhandlecatch:system"));
            generation=next;state="READY";return true;
        } catch(SemanticUnavailableException unavailable){state="UNAVAILABLE_KEYWORD_ONLY";return false;}
    }
    /** A Qdrant manifest is a new target proof, never a renamed Chroma/hash256 manifest. */
    public void attachPreservedCollection() {
        try {
            byte[] raw=RagPreservationManifest.privateBytes(properties,16*1024*1024);
            var proof=json.copy().enable(com.fasterxml.jackson.core.JsonParser.Feature.STRICT_DUPLICATE_DETECTION).readTree(raw);var identity=proof.path("identity");
            if(!proof.path("schemaVersion").isIntegralNumber()||proof.path("schemaVersion").asInt()!=2||!"QDRANT_RAG_TARGET".equals(proof.path("kind").asText())
                    ||!"VERIFIED".equals(proof.path("status").asText())||!"qdrant".equals(identity.path("backend").asText())
                    ||!semantic.getRagCollection().equals(identity.path("collection").asText())
                    ||!semantic.getModel().equals(identity.path("model").asText())||!semantic.getProfile().equals(identity.path("profile").asText())
                    ||identity.path("dimensions").asInt()!=semantic.getDimensions()
                    ||!semantic.getPreprocessing().equals(identity.path("preprocessing").asText())
                    ||!semantic.getStorageGeneration().equals(identity.path("storageGeneration").asText())
                    ||!"doorhandle-vector-sha256-v8-v1".equals(identity.path("idProtocol").asText())
                    ||!properties.getRagPreservationCommit().equals(proof.path("commit").asText())
                    ||!proof.path("records").isArray()||proof.path("records").isEmpty()||proof.path("records").size()>1000)throw new IllegalArgumentException();
            var records=new ArrayList<SemanticVectorStore.Document>();
            var storedProof=new java.util.LinkedHashMap<String,String>();
            for(var row:proof.path("records")) {
                if(!row.path("id").isTextual()||row.path("id").asText().isBlank()||!row.path("text").isTextual()||row.path("text").asText().isBlank()||!row.path("metadata").isObject())throw new IllegalArgumentException();
                var metadata=new java.util.LinkedHashMap<String,String>();row.path("metadata").fields().forEachRemaining(entry->{if(!entry.getValue().isTextual())throw new IllegalArgumentException();metadata.put(entry.getKey(),entry.getValue().asText());});
                records.add(new SemanticVectorStore.Document(row.path("id").asText(),row.path("text").asText(),metadata));
                String rawVector=row.path("rawVectorSha256").asText(),storedVector=row.path("storedVectorSha256").asText();
                if(!rawVector.matches("[a-f0-9]{64}")||!storedVector.matches("[a-f0-9]{64}")||!row.path("cosineNormalizationVerified").asBoolean()
                        ||storedProof.put(row.path("id").asText(),storedVector)!=null)throw new IllegalArgumentException();
            }
            String admitted=identity.path("generation").asText();
            if(admitted.isBlank()||records.stream().anyMatch(doc->!admitted.equals(doc.metadata().get("generation"))||!"SYSTEM_RAG".equals(doc.metadata().get("kind"))||!"SYSTEM".equals(doc.metadata().get("visibility"))||!"ACTIVE".equals(doc.metadata().get("lifecycle")))
                    ||store.count(semantic.getRagCollection(),SemanticVectorStore.Filter.all(Map.of("kind","SYSTEM_RAG","generation",admitted)))!=records.size()
                    ||!store.contains(semantic.getRagCollection(),records)||!storedProof.equals(store.storedFingerprints(semantic.getRagCollection(),records)))throw new IllegalArgumentException();
            generation=admitted;state="READY";
        } catch(Exception invalid){state="PRESERVATION_REJECTED";throw new IllegalStateException("Qdrant RAG target preservation proof rejected");}
    }
    public List<RagDocument> query(String query,int limit) {
        if(!enabled()||generation==null)return List.of();
        try {
            var hits=store.search(semantic.getRagCollection(),query,SemanticVectorStore.Filter.all(Map.of("kind","SYSTEM_RAG","generation",generation,"visibility","SYSTEM","lifecycle","ACTIVE")),limit,new EmbeddingClient.RequestContext("SYSTEM_RAG","doorhandlecatch:system"));
            state="READY";return hits.stream().map(hit->new RagDocument(hit.id(),hit.metadata().getOrDefault("source",""),hit.metadata().getOrDefault("title",""),hit.text())).toList();
        }catch(SemanticUnavailableException|IllegalArgumentException unavailable){state="UNAVAILABLE_KEYWORD_ONLY";return List.of();}
    }
}
