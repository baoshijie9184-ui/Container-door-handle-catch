package com.ruanzhu.doorhandle.module.app.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.semantic.*;
import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class QdrantRagStoreServiceTest {
    @TempDir Path directory;
    private final ObjectMapper json=new ObjectMapper();
    private final SemanticProperties semantic=new SemanticProperties();
    private final ChatAssistantProperties properties=new ChatAssistantProperties();
    private final SemanticVectorStore vectors=mock(SemanticVectorStore.class);
    private Map<String,Object> proof(){
        var identity=new LinkedHashMap<String,Object>();identity.put("backend","qdrant");identity.put("collection",semantic.getRagCollection());identity.put("model",semantic.getModel());identity.put("profile",semantic.getProfile());identity.put("dimensions",1024);identity.put("preprocessing",semantic.getPreprocessing());identity.put("storageGeneration",semantic.getStorageGeneration());identity.put("generation","candidate-generation");identity.put("idProtocol","doorhandle-vector-sha256-v8-v1");
        return new LinkedHashMap<>(Map.of("schemaVersion",2,"kind","QDRANT_RAG_TARGET","status","VERIFIED","commit","b".repeat(40),"identity",identity,"records",List.of(Map.of("id","old-public-id","text","original system guide","metadata",Map.of("kind","SYSTEM_RAG","generation","candidate-generation","visibility","SYSTEM","lifecycle","ACTIVE","source","legacy-guide","title","原说明"),"rawVectorSha256","a".repeat(64),"storedVectorSha256","b".repeat(64),"cosineNormalizationVerified",true))));
    }
    private QdrantRagStoreService attach(Map<String,Object> proof)throws Exception{
        var path=directory.resolve("qdrant-target-proof.json");byte[] raw=json.writeValueAsBytes(proof);Files.write(path,raw);Files.setPosixFilePermissions(path,PosixFilePermissions.fromString("rw-------"));
        properties.setRagStartupMode(ChatAssistantProperties.RagStartupMode.PRESERVE_EXISTING);properties.setRagPreservationCommit("b".repeat(40));properties.setRagPreservationManifest(path.toString());properties.setRagPreservationManifestSha256(RagPreservationManifest.sha(raw));
        return new QdrantRagStoreService(vectors,semantic,properties,json);
    }
    @Test void preservedTargetRequiresCompleteStoredProofAndNeverReembedsOrMutates()throws Exception{
        when(vectors.count(anyString(),any())).thenReturn(1L);when(vectors.contains(anyString(),anyList())).thenReturn(true);when(vectors.storedFingerprints(anyString(),anyList())).thenReturn(Map.of("old-public-id","b".repeat(64)));
        var store=attach(proof());store.attachPreservedCollection();assertThat(store.state()).isEqualTo("READY");verify(vectors,never()).upsert(anyString(),anyList(),any());
    }
    @Test void extraGenerationMembersOrChangedStoredVectorsRejectPreservation()throws Exception{
        when(vectors.count(anyString(),any())).thenReturn(2L);when(vectors.contains(anyString(),anyList())).thenReturn(true);when(vectors.storedFingerprints(anyString(),anyList())).thenReturn(Map.of("old-public-id","b".repeat(64)));
        var extra=attach(proof());assertThatThrownBy(extra::attachPreservedCollection).hasMessageContaining("proof rejected");
        when(vectors.count(anyString(),any())).thenReturn(1L);when(vectors.storedFingerprints(anyString(),anyList())).thenReturn(Map.of("old-public-id","c".repeat(64)));
        var changed=attach(proof());assertThatThrownBy(changed::attachPreservedCollection).hasMessageContaining("proof rejected");verify(vectors,never()).upsert(anyString(),anyList(),any());
    }
    @Test void oldHash256ManifestCannotBeRelabeledAsBgeTarget()throws Exception{
        var old=proof();old.put("schemaVersion",1);old.put("kind","doorhandle-rag-preservation-v1");var store=attach(old);
        assertThatThrownBy(store::attachPreservedCollection).hasMessageContaining("proof rejected");verifyNoInteractions(vectors);
    }
}
