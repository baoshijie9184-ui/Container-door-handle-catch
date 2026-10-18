package com.ruanzhu.doorhandle.module.app.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.system.security.SensitiveDataSanitizer;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.*;

/**
 * mem0 记忆服务客户端
 * 调用 Python mem0 服务进行记忆管理
 */
@Slf4j
@Service
public class Mem0Client {

    @Value("${mem0.service-url:http://localhost:8081}")
    private String serviceUrl;

    @Value("${mem0.enabled:true}")
    private boolean enabled;

    @Value("${mem0.connect-timeout-ms:2000}")
    private int connectTimeoutMs;

    @Value("${mem0.read-timeout-ms:5000}")
    private int readTimeoutMs;

    private final SensitiveDataSanitizer sensitiveDataSanitizer;
    private final MemoryPreferenceService preferences;
    @Value("${mem0.bridge-token:}")
    private String bridgeToken;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public Mem0Client(SensitiveDataSanitizer sensitiveDataSanitizer) {
        this(sensitiveDataSanitizer, null);
    }
    @org.springframework.beans.factory.annotation.Autowired
    public Mem0Client(SensitiveDataSanitizer sensitiveDataSanitizer, MemoryPreferenceService preferences) {
        this.sensitiveDataSanitizer = sensitiveDataSanitizer;
        this.preferences = preferences;
    }

    /**
     * 添加记忆
     */
    public Map<String, Object> addMemory(TenantContext tenant, String sessionId,
                                         String content, Map<String, Object> metadata) {
        if (!allowed(tenant, false)) return Collections.emptyMap();
        var scope=buildScope(tenant,sessionId);
        String sanitized=sensitiveDataSanitizer.sanitize(content);
        String turn=metadata!=null&&metadata.get("turn_id")!=null?metadata.get("turn_id").toString():sanitized;
        String requestId=sha256(tenant.mem0UserId()+"\u0000doorhandlecatch\u0000"+sessionId+"\u0000"+turn);
        try {
            if(preferences!=null&&preferences.reserveAutomatic(tenant,requestId,sha256(sanitized)))return Map.of("replayed",true);
        }catch(RuntimeException error){log.warn("记忆提炼未派发，审计未通过：errorType={}",error.getClass().getSimpleName());return Collections.emptyMap();}
        return addMemory(tenant,scope,sanitized,metadata,requestId);
    }

    private Map<String, Object> addMemory(TenantContext tenant,Map<String, Object> scope, String content,
                                          Map<String, Object> metadata,String requestId) {
        if (!enabled) return Collections.emptyMap();

        try {
            Map<String, Object> body = new HashMap<>();
            body.putAll(scope);
            body.put("content", content);
            body.put("request_id",requestId);
            if (metadata != null) {
                body.put("metadata", metadata);
            }

            HttpHeaders headers = bridgeHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            HttpEntity<Map<String, Object>> request = new HttpEntity<>(body, headers);

            ResponseEntity<JsonNode> response = restTemplate().exchange(
                    serviceUrl + "/memories/add",
                    HttpMethod.POST,
                    request,
                    JsonNode.class
            );

            if (response.getStatusCode().is2xxSuccessful() && response.getBody() != null) {
                if(!Set.of(200,202).contains(response.getStatusCode().value())||response.getBody().path("code").asInt()!=response.getStatusCode().value())throw new IllegalStateException("Memory receipt envelope is invalid");
                JsonNode data = response.getBody().path("data");
                String state=data.path("operation").path("status").asText();
                if(!requestId.equals(data.path("operation").path("requestId").asText())||!Set.of("SUCCEEDED","RUNNING","NEEDS_REVIEW","NOT_STARTED").contains(state))throw new IllegalStateException("Memory receipt is missing");
                if ("SUCCEEDED".equals(state)) {
                    if(preferences!=null)preferences.deletionOutcome(tenant,requestId,"SUCCEEDED");
                    log.info("记忆提炼已核对: userId={}", scope.get("user_id"));
                    return objectMapper.convertValue(data, Map.class);
                }
                log.info("记忆提炼等待核对: userId={},state={}",scope.get("user_id"),state);
                return Map.of("requestId",requestId,"status",state);
            }
        } catch (Exception e) {
            boolean notStarted=e instanceof org.springframework.web.client.HttpStatusCodeException status&&(Set.of(400,422).contains(status.getStatusCode().value())||status.getStatusCode().value()==503&&status.getResponseHeaders()!=null&&"false".equals(status.getResponseHeaders().getFirst("X-Memory-Operation-Started")));
            if(preferences!=null)try{preferences.deletionOutcome(tenant,requestId,notStarted?"REJECTED":"UNKNOWN");}catch(RuntimeException audit){log.warn("提炼回执待核对：errorType={}",audit.getClass().getSimpleName());}
            log.warn("记忆提炼结果待核对，不自动重做：errorType={}", e.getClass().getSimpleName());
        }
        return Collections.emptyMap();
    }

    private static String sha256(String value){try{return HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(value.getBytes(java.nio.charset.StandardCharsets.UTF_8)));}catch(java.security.NoSuchAlgorithmException error){throw new IllegalStateException(error);}}

    public com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos.Extraction extractionReceipt(TenantContext owner,String requestId){
        if(!enabled||bridgeToken==null||bridgeToken.isBlank())throw new org.springframework.web.server.ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"记忆回执服务尚未启用");
        try{
            var response=restTemplate().exchange(serviceUrl+"/memories/operations/get",HttpMethod.POST,new HttpEntity<>(Map.of("user_id",owner.mem0UserId(),"app_id","doorhandlecatch","request_id",requestId),bridgeHeaders()),JsonNode.class);
            var root=response.getBody();if(root==null||root.path("code").asInt()!=200)throw new IllegalStateException();var data=root.path("data");String state=data.path("status").asText();
            if(!requestId.equals(data.path("requestId").asText())||!Set.of("RUNNING","SUCCEEDED","NEEDS_REVIEW","NOT_STARTED").contains(state)||!data.path("results").isArray()||data.path("results").size()>100)throw new IllegalStateException();
            return new com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos.Extraction(requestId,state,"SUCCEEDED".equals(state)?data.path("results").size():null,data.path("updatedAt").asText(null));
        }catch(Exception error){throw new org.springframework.web.server.ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"提炼回执暂不可用，请稍后核对；不会重新执行");}
    }

    /**
     * 搜索记忆
     */
    public List<Map<String, Object>> searchMemories(TenantContext tenant, String sessionId,
                                                     String query, int topK) {
        if (!allowed(tenant, true)) return Collections.emptyList();
        return searchMemories(buildScope(tenant, sessionId), query, topK);
    }

    /** 长期记忆跨会话检索，但始终保留当前账号与应用过滤；来源会话仍用于追溯。 */
    public List<Map<String, Object>> searchAccountMemories(TenantContext tenant, String sessionId, String query, int topK) {
        if (!allowed(tenant, true)) return Collections.emptyList();
        var scope = new HashMap<>(buildScope(tenant, sessionId));
        scope.put("scope", "ACCOUNT");
        return searchMemories(scope, query, topK);
    }

    private List<Map<String, Object>> searchMemories(Map<String, Object> scope, String query, int topK) {
        if (!enabled) return Collections.emptyList();

        try {
            Map<String, Object> body = new HashMap<>();
            body.putAll(scope);
            body.put("query", query);
            body.put("top_k", topK);

            HttpHeaders headers = bridgeHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            HttpEntity<Map<String, Object>> request = new HttpEntity<>(body, headers);

            ResponseEntity<JsonNode> response = restTemplate().exchange(
                    serviceUrl + "/memories/search",
                    HttpMethod.POST,
                    request,
                    JsonNode.class
            );

            if (response.getStatusCode().is2xxSuccessful() && response.getBody() != null) {
                JsonNode data = response.getBody().get("data");
                if (data != null && data.isArray()) {
                    List<Map<String, Object>> memories = new ArrayList<>();
                    for (JsonNode item : data) {
                        Map<String, Object> memory = new HashMap<>();
                        memory.put("id", item.path("id").asText(""));
                        memory.put("memory", item.path("memory").asText(""));
                        memory.put("score", item.path("score").asDouble(0));
                        if (item.has("metadata") && !item.get("metadata").isNull()) {
                            memory.put("metadata", objectMapper.convertValue(item.get("metadata"), Map.class));
                        }
                        memories.add(memory);
                    }
                    log.debug("搜索到 {} 条记忆: userId={}", memories.size(), scope.get("user_id"));
                    return memories;
                }
            }
        } catch (Exception e) {
            log.warn("搜索记忆失败 (服务可能未启动): {}", e.getClass().getSimpleName());
        }
        return Collections.emptyList();
    }

    public com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos.Page listOwned(TenantContext owner, int limit) {
        return listOwned(owner,limit,0);
    }
    public com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos.Page listOwned(TenantContext owner, int limit, int offset) {
        var data = ownedRequest("list", Map.of("user_id", owner.mem0UserId(), "app_id", "doorhandlecatch", "limit", limit,"offset",offset));
        try {
            var page = objectMapper.treeToValue(data, com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos.Page.class);
            if (page.items() == null || page.items().size() > limit) throw new IllegalArgumentException();
            if (page.hasMore() && (page.nextOffset() == null || page.nextOffset() <= offset || page.nextOffset() > (long)offset + limit)) throw new IllegalArgumentException();
            return page;
        } catch (Exception ignored) { throw new org.springframework.web.server.ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "记忆服务返回格式不正确"); }
    }
    public com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos.Item getOwned(TenantContext owner,String id) {
        var data=ownedRequest("get",Map.of("user_id",owner.mem0UserId(),"app_id","doorhandlecatch","memory_id",id));
        try {
            var item=objectMapper.treeToValue(data,com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos.Item.class);
            if(!id.equals(item.id())||item.memory()==null||item.digest()==null||!item.digest().matches("[a-f0-9]{64}"))throw new IllegalArgumentException();
            return item;
        } catch(Exception error) { throw new org.springframework.web.server.ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"记忆服务返回格式不正确"); }
    }
    public void deleteOwned(TenantContext owner, String id, String digest) {
        var data = ownedRequest("delete", Map.of("user_id", owner.mem0UserId(), "app_id", "doorhandlecatch", "memory_id", id, "expected_digest", digest));
        if (!data.path("deleted").asBoolean()) throw new org.springframework.web.server.ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "删除结果待核对，请刷新记忆列表");
    }
    public void updateOwned(TenantContext owner, String id, String digest, String content) {
        var data = ownedRequest("update", Map.of("user_id",owner.mem0UserId(),"app_id","doorhandlecatch","memory_id",id,"expected_digest",digest,"memory",content));
        if (!data.path("updated").asBoolean()) throw new org.springframework.web.server.ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"修改结果待核对，请刷新记忆列表");
    }
    private JsonNode ownedRequest(String operation, Map<String,Object> body) {
        if (!enabled || bridgeToken == null || bridgeToken.isBlank()) throw new org.springframework.web.server.ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "记忆服务未启用或桥接认证未配置");
        try {
            var response = restTemplate().exchange(serviceUrl + "/memories/owned/" + operation, HttpMethod.POST, new HttpEntity<>(body, bridgeHeaders()), JsonNode.class);
            if (response.getBody() == null || response.getBody().path("code").asInt() != 200 || !response.getBody().has("data")) throw new IllegalStateException();
            return response.getBody().get("data");
        } catch (org.springframework.web.client.HttpClientErrorException error) {
            int code = error.getStatusCode().value();
            if (code == 404) throw new org.springframework.web.server.ResponseStatusException(HttpStatus.NOT_FOUND, "记忆不可用");
            if (code == 409) throw new org.springframework.web.server.ResponseStatusException(HttpStatus.CONFLICT, "记忆已变化，请刷新核对后再操作");
            if (code == 422) throw new org.springframework.web.server.ResponseStatusException(HttpStatus.BAD_REQUEST, "记忆操作参数不正确");
            throw new org.springframework.web.server.ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "记忆服务认证或访问暂不可用");
        } catch (Exception error) {
            throw new org.springframework.web.server.ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "记忆服务暂不可用；操作结果需要刷新核对");
        }
    }
    private HttpHeaders bridgeHeaders() {
        var headers = new HttpHeaders(); headers.setContentType(MediaType.APPLICATION_JSON);
        if (bridgeToken != null && !bridgeToken.isBlank()) headers.set("X-Doorhandle-Memory-Token", bridgeToken);
        return headers;
    }
    private boolean allowed(TenantContext owner, boolean read) {
        if (!enabled) return false;
        if (preferences == null) return true;
        try { var settings = preferences.get(owner); return read ? settings.readEnabled() : settings.saveEnabled(); }
        catch (RuntimeException error) { log.warn("记忆设置读取失败，已跳过记忆：errorType={}", error.getClass().getSimpleName()); return false; }
    }

    /**
     * 异步添加记忆（不阻塞主流程）
     */
    @Async
    public void addMemoryAsync(TenantContext tenant, String sessionId, String content,
                               Map<String, Object> metadata) {
        addMemory(tenant, sessionId, content, metadata);
    }

    Map<String, Object> buildScope(TenantContext tenant, String sessionId) {
        if (tenant == null || sessionId == null || sessionId.isBlank()) {
            throw new IllegalArgumentException("tenant and sessionId are required");
        }
        return Map.of(
                "user_id", tenant.mem0UserId(),
                "app_id", "doorhandlecatch",
                "run_id", sessionId
        );
    }

    private RestTemplate restTemplate() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(connectTimeoutMs);
        factory.setReadTimeout(readTimeoutMs);
        return new RestTemplate(factory);
    }

    /**
     * 将记忆列表格式化为上下文文本
     */
    public String formatMemoriesAsContext(List<Map<String, Object>> memories) {
        if (memories == null || memories.isEmpty()) {
            return "";
        }

        StringBuilder sb = new StringBuilder("[用户历史记忆]\n");
        for (Map<String, Object> memory : memories) {
            String content = (String) memory.get("memory");
            if (content != null && !content.isEmpty()) {
                sb.append("- ").append(content).append("\n");
            }
        }
        return sb.toString();
    }
}
