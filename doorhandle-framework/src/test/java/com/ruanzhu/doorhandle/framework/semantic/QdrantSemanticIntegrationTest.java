package com.ruanzhu.doorhandle.framework.semantic;

import io.qdrant.client.QdrantClient;
import io.qdrant.client.QdrantGrpcClient;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Assumptions;
import static org.assertj.core.api.Assertions.*;

/** Actual official SDK/server integration on the existing ECS fixture, with no provider requests. */
class QdrantSemanticIntegrationTest {
    @Test void denseNativeRoundtripNamespaceAuthFiltersAndReopenKeepExactStoredProof() throws Exception {
        String host=System.getProperty("doorhandle.qdrant.host",System.getenv().getOrDefault("DOORHANDLE_TEST_QDRANT_HOST",""));
        if(Boolean.getBoolean("doorhandle.qdrant.required")||"true".equals(System.getenv("DOORHANDLE_REQUIRE_QDRANT_TESTS")))assertThat(host).as("Required ECS Qdrant fixture").isNotBlank();
        Assumptions.assumeTrue(!host.isBlank(),"ECS-only Qdrant fixture is not configured");
        var properties=new SemanticProperties();properties.setQdrantHost(host);
        properties.setQdrantGrpcPort(Integer.parseInt(System.getProperty("doorhandle.qdrant.grpc.port",System.getenv().getOrDefault("DOORHANDLE_TEST_QDRANT_GRPC_PORT","6334"))));
        properties.setQdrantTls(Boolean.parseBoolean(System.getProperty("doorhandle.qdrant.tls",System.getenv().getOrDefault("DOORHANDLE_TEST_QDRANT_TLS","false"))));
        properties.setQdrantApiKeyFile(System.getProperty("doorhandle.qdrant.api-key-file",System.getenv().getOrDefault("DOORHANDLE_TEST_QDRANT_KEY_FILE","")));
        properties.setProfile("explicit-openai-compatible");properties.setModel("fixture-model");properties.setStorageGeneration("qdrant-explicit-test-v1");
        String collection="doorhandle_test_semantic_"+UUID.randomUUID().toString().replace("-","");properties.setRagCollection(collection);
        EmbeddingClient embedder=(texts,context)->texts.stream().map(text->{var vector=new java.util.ArrayList<Float>(Collections.nCopies(1024,0f));vector.set(0,2f);return List.copyOf(vector);}).toList();
        var context=new EmbeddingClient.RequestContext("SYSTEM_RAG","doorhandlecatch:system");
        var own=new SemanticVectorStore.Document("legacy-public-id","current source",Map.of("kind","SYSTEM_RAG","owner","42","version","1"));
        var foreign=new SemanticVectorStore.Document("foreign-public-id","foreign source",Map.of("kind","SYSTEM_RAG","owner","43","version","1"));
        var store=new QdrantSemanticVectorStore(properties,embedder);
        var cleanupBuilder=QdrantGrpcClient.newBuilder(host,properties.getQdrantGrpcPort(),properties.isQdrantTls());
        if(!properties.getQdrantApiKeyFile().isBlank())cleanupBuilder.withApiKey(Files.readString(Path.of(properties.getQdrantApiKeyFile())).strip());
        try(var cleanup=new QdrantClient(cleanupBuilder.build())) {
            try {
                store.upsert(collection,List.of(own,foreign),context);
                assertThat(store.contains(collection,List.of(own,foreign))).isTrue();
                var proof=store.storedFingerprints(collection,List.of(own,foreign));
                assertThat(proof).hasSize(2).allSatisfy((id,digest)->assertThat(digest).matches("[a-f0-9]{64}"));
                assertThat(store.search(collection,"same direction",SemanticVectorStore.Filter.all(Map.of("owner","42")),5,context))
                        .extracting(SemanticVectorStore.Hit::id).containsExactly("legacy-public-id");
                store.close();store=new QdrantSemanticVectorStore(properties,embedder);
                store.verifyCollection(collection);
                assertThat(store.storedFingerprints(collection,List.of(own,foreign))).isEqualTo(proof);
                var different=new SemanticProperties();different.setQdrantHost(host);different.setQdrantGrpcPort(properties.getQdrantGrpcPort());different.setQdrantApiKeyFile(properties.getQdrantApiKeyFile());different.setQdrantTls(properties.isQdrantTls());different.setRagCollection(collection);
                var rejected=new QdrantSemanticVectorStore(different,embedder);
                try{assertThatThrownBy(()->rejected.verifyCollection(collection)).isInstanceOf(SemanticUnavailableException.class).hasMessage("VECTOR_SPACE_IDENTITY_MISMATCH");}finally{rejected.close();}
            } finally {
                store.close();
                assertThat(collection).startsWith("doorhandle_test_semantic_");
                cleanup.deleteCollectionAsync(collection).get(10,TimeUnit.SECONDS);
            }
        }
    }
}
