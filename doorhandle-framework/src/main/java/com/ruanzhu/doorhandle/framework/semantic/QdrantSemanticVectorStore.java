package com.ruanzhu.doorhandle.framework.semantic;

import static io.qdrant.client.ConditionFactory.matchKeyword;
import static io.qdrant.client.PointIdFactory.id;
import static io.qdrant.client.ValueFactory.value;
import static io.qdrant.client.VectorsFactory.vectors;

import io.qdrant.client.QdrantClient;
import io.qdrant.client.QdrantGrpcClient;
import io.qdrant.client.grpc.Collections.CreateCollection;
import io.qdrant.client.grpc.Collections.Distance;
import io.qdrant.client.grpc.Collections.PayloadSchemaType;
import io.qdrant.client.grpc.Collections.VectorParams;
import io.qdrant.client.grpc.Collections.VectorsConfig;
import io.qdrant.client.grpc.Common.Condition;
import io.qdrant.client.grpc.JsonWithInt.Value;
import io.qdrant.client.grpc.Points.PointStruct;
import io.qdrant.client.grpc.Points.SearchPoints;
import io.qdrant.client.grpc.Points.UpsertPoints;
import io.qdrant.client.grpc.Points.WithPayloadSelector;
import jakarta.annotation.PreDestroy;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import org.springframework.stereotype.Component;

/** Official Qdrant SDK; an admitted collection is an explicit model/preprocessing/storage space. */
@Component
public final class QdrantSemanticVectorStore implements SemanticVectorStore {
    private final SemanticProperties properties;
    private final EmbeddingClient embedder;
    private QdrantClient client;
    public QdrantSemanticVectorStore(SemanticProperties properties,EmbeddingClient embedder) {
        this.properties=properties;this.embedder=embedder;
    }
    private synchronized QdrantClient client() {
        if(!properties.isEnabled())throw new SemanticUnavailableException("VECTOR_DISABLED");
        if(client==null) {
            var builder=QdrantGrpcClient.newBuilder(properties.getQdrantHost(),properties.getQdrantGrpcPort(),properties.isQdrantTls());
            if(properties.getQdrantApiKeyFile()!=null&&!properties.getQdrantApiKeyFile().isBlank()) {
                try {
                    Path path=Path.of(properties.getQdrantApiKeyFile());
                    if(!path.isAbsolute()||Files.isSymbolicLink(path)||!Files.isRegularFile(path)||Files.size(path)>4096)
                        throw new IllegalArgumentException();
                    String key=Files.readString(path).strip();
                    if(key.isBlank()||key.chars().anyMatch(Character::isWhitespace))throw new IllegalArgumentException();
                    builder.withApiKey(key);
                } catch(Exception invalid) {throw new SemanticUnavailableException("VECTOR_SECRET_INVALID");}
            }
            client=new QdrantClient(builder.build());
        }
        return client;
    }
    private <T> T await(Future<T> future) {
        try {return future.get(properties.getTimeoutSeconds(),TimeUnit.SECONDS);}
        catch(InterruptedException interrupted){Thread.currentThread().interrupt();throw new SemanticUnavailableException("VECTOR_INTERRUPTED");}
        catch(Exception failed){future.cancel(true);throw new SemanticUnavailableException("VECTOR_OPERATION_FAILED");}
    }
    private Duration timeout(){return Duration.ofSeconds(properties.getTimeoutSeconds());}
    private Map<String,Value> identity() {
        return Map.of("doorhandle_profile",value(properties.getProfile()),"doorhandle_model",value(properties.getModel()),
                "doorhandle_dimensions",value(properties.getDimensions()),"doorhandle_preprocessing",value(properties.getPreprocessing()),
                "doorhandle_storage_generation",value(properties.getStorageGeneration()),"doorhandle_metric",value("Cosine"),
                "doorhandle_id_protocol",value("doorhandle-vector-sha256-v8-v1"));
    }
    private void collectionName(String name) {
        if(!List.of(properties.getRagCollection(),properties.getKnowledgeCollection(),properties.getExperienceCollection()).contains(name)
                ||!name.matches("[A-Za-z0-9_-]{1,128}")) throw new IllegalArgumentException("Collection is not configured");
    }
    private synchronized void ensure(String collection,boolean create) {
        collectionName(collection);var sdk=client();
        if(properties.getTimeoutSeconds()<1||properties.getTimeoutSeconds()>120||properties.getDimensions()<32||properties.getDimensions()>8192
                ||!List.of("siliconflow-bge-m3-v1","explicit-openai-compatible").contains(properties.getProfile())
                ||!"utf8-newline-space-v1".equals(properties.getPreprocessing())
                ||("siliconflow-bge-m3-v1".equals(properties.getProfile())&&(!"BAAI/bge-m3".equals(properties.getModel())||properties.getDimensions()!=1024||!"qdrant-bge-m3-v1".equals(properties.getStorageGeneration())))
                ||("explicit-openai-compatible".equals(properties.getProfile())&&!"qdrant-explicit-test-v1".equals(properties.getStorageGeneration())))
            throw new SemanticUnavailableException("VECTOR_CONFIG_IDENTITY_MISMATCH");
        boolean exists=await(sdk.collectionExistsAsync(collection));
        if(!exists) {
            if(!create)throw new SemanticUnavailableException("VECTOR_COLLECTION_NOT_ADMITTED");
            await(sdk.createCollectionAsync(CreateCollection.newBuilder().setCollectionName(collection)
                    .setVectorsConfig(VectorsConfig.newBuilder().setParams(VectorParams.newBuilder()
                            .setSize(properties.getDimensions()).setDistance(Distance.Cosine).setOnDisk(true)))
                    .putAllMetadata(identity()).build(),timeout()));
            // Filter indexes precede ingestion; no full-text/sparse model is downloaded.
            for(String key:List.of("kind","owner","visibility","role","source_id","version","lifecycle","generation","logical_id"))
                await(sdk.createPayloadIndexAsync(collection,key,PayloadSchemaType.Keyword,null,true,null,timeout()));
        }
        var info=await(sdk.getCollectionInfoAsync(collection,timeout()));
        var params=info.getConfig().getParams().getVectorsConfig();
        if(!params.hasParams()||params.getParams().getSize()!=properties.getDimensions()
                ||params.getParams().getDistance()!=Distance.Cosine
                ||!info.getConfig().getMetadataMap().entrySet().containsAll(identity().entrySet()))
            throw new SemanticUnavailableException("VECTOR_SPACE_IDENTITY_MISMATCH");
    }
    @Override public void verifyCollection(String collection){ensure(collection,false);}
    private Map<String,Value> payload(Document document) {
        if(document.id()==null||document.id().isBlank()||document.id().length()>512||document.text()==null||document.text().isBlank()||document.text().getBytes(java.nio.charset.StandardCharsets.UTF_8).length>8000)
            throw new IllegalArgumentException("Invalid semantic document");
        var payload=new LinkedHashMap<String,Value>();
        document.metadata().forEach((key,item)->{if(List.of("logical_id","text").contains(key))throw new IllegalArgumentException("Reserved vector payload");payload.put(key,value(item));});
        payload.put("logical_id",value(document.id()));payload.put("text",value(document.text()));return payload;
    }
    @Override public void upsert(String collection,List<Document> documents,EmbeddingClient.RequestContext context) {
        SemanticTelemetry.call("vector.upsert",context.purpose(),properties.getModel(),()->{upsertDocuments(collection,documents,context);return null;});
    }
    private void upsertDocuments(String collection,List<Document> documents,EmbeddingClient.RequestContext context) {
        if(documents.isEmpty())return;
        // Validate all records and finish all provider calls before modifying the remote index.
        var payloads=documents.stream().map(this::payload).toList();
        if(documents.stream().map(Document::id).distinct().count()!=documents.size())throw new IllegalArgumentException("Duplicate vector logical identity");
        ensure(collection,true); // Reject a foreign/unmarked space before spending any embedding request.
        var embeddings=new ArrayList<List<Float>>();
        for(int offset=0;offset<documents.size();offset+=64)
            embeddings.addAll(embedder.embed(documents.subList(offset,Math.min(offset+64,documents.size())).stream().map(Document::text).toList(),context));
        if(embeddings.size()!=documents.size())throw new SemanticUnavailableException("EMBEDDING_CARDINALITY_MISMATCH");
        embeddings.forEach(this::validateEmbedding);
        for(int offset=0;offset<documents.size();offset+=64) {
            var points=new ArrayList<PointStruct>();
            for(int n=offset;n<Math.min(offset+64,documents.size());n++)points.add(PointStruct.newBuilder()
                    .setId(id(SemanticDocuments.pointId(collection,documents.get(n).id())))
                    .setVectors(vectors(embeddings.get(n))).putAllPayload(payloads.get(n)).build());
            await(client().upsertAsync(UpsertPoints.newBuilder().setCollectionName(collection).setWait(true).addAllPoints(points).build(),timeout()));
        }
        if(!contains(collection,documents))throw new SemanticUnavailableException("VECTOR_WRITE_READBACK_MISMATCH");
        // Cosine upload is normalized by Qdrant. Compare the mathematical direction, not raw byte hashes.
        var stored=readVectors(collection,documents);
        for(int n=0;n<documents.size();n++) {
            var raw=embeddings.get(n);var actual=stored.get(documents.get(n).id());double norm=0;
            for(float item:raw)norm+=(double)item*item;norm=Math.sqrt(norm);
            for(int i=0;i<raw.size();i++)if(Math.abs(raw.get(i)/norm-actual.get(i))>3e-6)
                throw new SemanticUnavailableException("VECTOR_COSINE_NORMALIZATION_MISMATCH");
        }
    }
    private io.qdrant.client.grpc.Common.Filter filter(Filter filter) {
        var builder=io.qdrant.client.grpc.Common.Filter.newBuilder();
        filter.all().forEach((key,item)->builder.addMust(matchKeyword(key,item)));
        for(var alternative:filter.any()) {
            var child=io.qdrant.client.grpc.Common.Filter.newBuilder();
            alternative.forEach((key,item)->child.addMust(matchKeyword(key,item)));
            builder.addShould(Condition.newBuilder().setFilter(child));
        }
        return builder.build();
    }
    private Map<String,String> metadata(Map<String,Value> payload) {
        var result=new LinkedHashMap<String,String>();payload.forEach((key,item)->{if(!List.of("logical_id","text").contains(key))result.put(key,item.getStringValue());});return Map.copyOf(result);
    }
    @Override public List<Hit> search(String collection,String query,Filter filter,int limit,EmbeddingClient.RequestContext context) {
        return SemanticTelemetry.call("vector.query",context.purpose(),properties.getModel(),()->query(collection,query,filter,limit,context));
    }
    private List<Hit> query(String collection,String query,Filter filter,int limit,EmbeddingClient.RequestContext context) {
        if(limit<1||limit>100)throw new IllegalArgumentException("Invalid semantic result bound");
        ensure(collection,false);var vector=embedder.embed(List.of(query),context).get(0);
        validateEmbedding(vector);
        return await(client().searchAsync(SearchPoints.newBuilder().setCollectionName(collection).addAllVector(vector)
                .setFilter(filter(filter)).setLimit(limit).setWithPayload(WithPayloadSelector.newBuilder().setEnable(true)).build(),timeout()))
                .stream().map(point->{var p=point.getPayloadMap();return new Hit(p.getOrDefault("logical_id",Value.getDefaultInstance()).getStringValue(),point.getScore(),p.getOrDefault("text",Value.getDefaultInstance()).getStringValue(),metadata(p));}).toList();
    }
    @Override public boolean contains(String collection,List<Document> documents) {
        ensure(collection,false);
        for(int offset=0;offset<documents.size();offset+=64) {
            var batch=documents.subList(offset,Math.min(offset+64,documents.size()));
            var found=await(client().retrieveAsync(collection,batch.stream().map(doc->id(SemanticDocuments.pointId(collection,doc.id()))).toList(),true,true,null));
            if(found.size()!=batch.size())return false;
            var expected=new LinkedHashMap<String,Map<String,Value>>();batch.forEach(doc->expected.put(SemanticDocuments.pointId(collection,doc.id()).toString(),payload(doc)));
            for(var row:found){if(!row.getPayloadMap().equals(expected.get(row.getId().getUuid())))return false;validateVector(row.getVectors());}
        }
        return true;
    }
    private List<Float> validateVector(io.qdrant.client.grpc.Points.VectorsOutput output) {
        var vector=output.getVector();var data=vector.hasDense()?vector.getDense().getDataList():vector.getDataList();
        if(data.size()!=properties.getDimensions())throw new SemanticUnavailableException("VECTOR_STORED_DIMENSION_MISMATCH");
        double norm=0;for(float item:data){if(!Float.isFinite(item))throw new SemanticUnavailableException("VECTOR_STORED_NONFINITE");norm+=(double)item*item;}
        if(Math.abs(norm-1)>2e-5)throw new SemanticUnavailableException("VECTOR_STORED_NOT_NORMALIZED");return data;
    }
    private void validateEmbedding(List<Float> vector) {
        if(vector==null||vector.size()!=properties.getDimensions())throw new SemanticUnavailableException("EMBEDDING_DIMENSION_MISMATCH");
        double norm=0;for(Float item:vector){if(item==null||!Float.isFinite(item))throw new SemanticUnavailableException("EMBEDDING_INVALID_VECTOR");norm+=(double)item*item;}
        if(norm==0)throw new SemanticUnavailableException("EMBEDDING_ZERO_VECTOR");
    }
    private Map<String,List<Float>> readVectors(String collection,List<Document> documents) {
        ensure(collection,false);var result=new LinkedHashMap<String,List<Float>>();
        for(int offset=0;offset<documents.size();offset+=64){var batch=documents.subList(offset,Math.min(offset+64,documents.size()));
            var rows=await(client().retrieveAsync(collection,batch.stream().map(doc->id(SemanticDocuments.pointId(collection,doc.id()))).toList(),true,true,null));
            for(var row:rows){String logical=row.getPayloadMap().getOrDefault("logical_id",Value.getDefaultInstance()).getStringValue();
                if(!SemanticDocuments.pointId(collection,logical).toString().equals(row.getId().getUuid())||result.put(logical,validateVector(row.getVectors()))!=null)throw new SemanticUnavailableException("VECTOR_STORED_ID_MISMATCH");}
        }
        if(result.size()!=documents.size())throw new SemanticUnavailableException("VECTOR_STORED_SET_MISMATCH");return result;
    }
    @Override public Map<String,String> storedFingerprints(String collection,List<Document> documents) {
        if(!contains(collection,documents))throw new SemanticUnavailableException("VECTOR_STORED_CONTENT_MISMATCH");
        var result=new LinkedHashMap<String,String>();
        readVectors(collection,documents).forEach((logical,vector)->{
            var buffer=ByteBuffer.allocate(vector.size()*Float.BYTES).order(ByteOrder.LITTLE_ENDIAN);vector.forEach(buffer::putFloat);
            try{result.put(logical,HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(buffer.array())));}
            catch(java.security.NoSuchAlgorithmException unavailable){throw new IllegalStateException(unavailable);}
        });return Map.copyOf(result);
    }
    @Override public long count(String collection,Filter filter){ensure(collection,false);return await(client().countAsync(collection,filter(filter),true,timeout()));}
    @PreDestroy public synchronized void close(){if(client!=null)client.close();}
}
