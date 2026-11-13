package com.ruanzhu.doorhandle.framework.semantic;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/** Reuses the Mem0 bridge's single FreeBgeEmbedder, request budget and secret mount. No retries. */
@Component
public final class MemoryBridgeEmbeddingClient implements EmbeddingClient {
    private final SemanticProperties properties;
    private final ObjectMapper json;
    private final URI endpoint;
    private final String token;
    private final HttpClient client;

    public MemoryBridgeEmbeddingClient(SemanticProperties properties, ObjectMapper json,
            @Value("${mem0.service-url:http://mem0:8081}") String serviceUrl,
            @Value("${mem0.bridge-token:}") String token) {
        this.properties=properties; this.json=json; this.token=token;
        URI base=URI.create(serviceUrl);
        if(!List.of("http","https").contains(base.getScheme())||base.getHost()==null
                ||base.getUserInfo()!=null||base.getQuery()!=null||base.getFragment()!=null)
            throw new IllegalArgumentException("Invalid internal embedding endpoint");
        endpoint=URI.create(serviceUrl.replaceAll("/+$","")+"/internal/embeddings");
        client=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3))
                .followRedirects(HttpClient.Redirect.NEVER).build();
    }

    @Override public List<List<Float>> embed(List<String> texts, RequestContext context) {
        return SemanticTelemetry.call("embedding.request",context==null?"UNKNOWN":context.purpose(),properties.getModel(),()->request(texts,context));
    }
    private List<List<Float>> request(List<String> texts, RequestContext context) {
        if(!properties.isEnabled()||token==null||token.isBlank()) throw new SemanticUnavailableException("EMBEDDING_DISABLED_OR_UNAUTHENTICATED");
        if(texts==null||texts.isEmpty()||texts.size()>64||context==null
                ||!List.of("SYSTEM_RAG","KNOWLEDGE","EXPERIENCE").contains(context.purpose())
                ||context.account()==null||!context.account().matches("doorhandlecatch:(system|user:[1-9][0-9]*)"))
            throw new IllegalArgumentException("Invalid embedding request context");
        for(String text:texts) if(text==null||text.isBlank()||text.getBytes(StandardCharsets.UTF_8).length>8000)
            throw new IllegalArgumentException("Embedding input exceeds its byte bound");
        if(properties.getEmbeddingTimeoutSeconds()<1||properties.getEmbeddingTimeoutSeconds()>120)throw new IllegalArgumentException("Invalid embedding timeout");
        var result=new ArrayList<List<Float>>();
        for(int offset=0;offset<texts.size();offset+=8)result.addAll(transport(texts.subList(offset,Math.min(offset+8,texts.size())),context));
        return List.copyOf(result);
    }
    private List<List<Float>> transport(List<String> texts,RequestContext context) {
        String requestId=UUID.randomUUID().toString();
        try {
            String body=json.writeValueAsString(Map.of("app_id","doorhandlecatch","purpose",context.purpose(),
                    "user_id",context.account(),"request_id",requestId,"texts",texts));
            var builder=HttpRequest.newBuilder(endpoint).timeout(Duration.ofSeconds(properties.getEmbeddingTimeoutSeconds()))
                    .header("Content-Type","application/json").header("x-doorhandle-memory-token",token)
                    .POST(HttpRequest.BodyPublishers.ofString(body,StandardCharsets.UTF_8));
            io.opentelemetry.api.GlobalOpenTelemetry.getPropagators().getTextMapPropagator().inject(
                    io.opentelemetry.context.Context.current(),builder,(carrier,key,item)->{if("traceparent".equalsIgnoreCase(key))carrier.header(key,item);});
            var request=builder.build();
            var response=client.send(request,HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if(response.statusCode()!=200||response.body().length()>4_000_000) throw new SemanticUnavailableException("EMBEDDING_BRIDGE_UNAVAILABLE");
            JsonNode data=json.readTree(response.body());
            if(data.path("schemaVersion").asInt()!=1||!requestId.equals(data.path("request_id").asText())
                    ||!properties.getProfile().equals(data.path("profile").asText())
                    ||!("siliconflow-bge-m3-v1".equals(properties.getProfile())?"siliconflow":"explicit-openai-compatible").equals(data.path("provider").asText())
                    ||!properties.getModel().equals(data.path("model").asText())
                    ||!properties.getPreprocessing().equals(data.path("preprocessing").asText())
                    ||data.path("dimensions").asInt()!=properties.getDimensions()
                    ||data.path("input_count").asInt()!=texts.size()||!data.path("vectors").isArray()
                    ||data.path("vectors").size()!=texts.size()) throw new SemanticUnavailableException("EMBEDDING_IDENTITY_MISMATCH");
            var vectors=new ArrayList<List<Float>>();
            for(JsonNode row:data.path("vectors")) {
                if(!row.isArray()||row.size()!=properties.getDimensions()) throw new SemanticUnavailableException("EMBEDDING_DIMENSION_MISMATCH");
                var values=new ArrayList<Float>(); double norm=0;
                for(JsonNode item:row) {float value=item.floatValue(); if(!item.isNumber()||!Float.isFinite(value))throw new SemanticUnavailableException("EMBEDDING_INVALID_VECTOR");values.add(value);norm+=(double)value*value;}
                if(norm==0)throw new SemanticUnavailableException("EMBEDDING_ZERO_VECTOR");
                vectors.add(List.copyOf(values));
            }
            return List.copyOf(vectors);
        } catch(InterruptedException interrupted) {Thread.currentThread().interrupt();throw new SemanticUnavailableException("EMBEDDING_INTERRUPTED");}
        catch(SemanticUnavailableException unavailable) {throw unavailable;}
        catch(Exception unavailable) {throw new SemanticUnavailableException("EMBEDDING_TRANSPORT_ERROR");}
    }
}
