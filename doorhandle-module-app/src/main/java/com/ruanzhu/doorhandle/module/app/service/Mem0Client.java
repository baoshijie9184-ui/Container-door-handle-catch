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
    private final ObjectMapper objectMapper = new ObjectMapper();

    public Mem0Client(SensitiveDataSanitizer sensitiveDataSanitizer) {
        this.sensitiveDataSanitizer = sensitiveDataSanitizer;
    }

    /**
     * 添加记忆
     */
    public Map<String, Object> addMemory(TenantContext tenant, String sessionId,
                                         String content, Map<String, Object> metadata) {
        return addMemory(buildScope(tenant, sessionId), content, metadata);
    }

    private Map<String, Object> addMemory(Map<String, Object> scope, String content,
                                          Map<String, Object> metadata) {
        if (!enabled) return Collections.emptyMap();

        try {
            Map<String, Object> body = new HashMap<>();
            body.putAll(scope);
            body.put("content", sensitiveDataSanitizer.sanitize(content));
            if (metadata != null) {
                body.put("metadata", metadata);
            }

            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            HttpEntity<Map<String, Object>> request = new HttpEntity<>(body, headers);

            ResponseEntity<JsonNode> response = restTemplate().exchange(
                    serviceUrl + "/memories/add",
                    HttpMethod.POST,
                    request,
                    JsonNode.class
            );

            if (response.getStatusCode().is2xxSuccessful() && response.getBody() != null) {
                JsonNode data = response.getBody().get("data");
                if (data != null) {
                    String safeContent = sensitiveDataSanitizer.sanitize(content);
                    log.info("记忆添加成功: userId={}, content={}", scope.get("user_id"), safeContent.substring(0, Math.min(50, safeContent.length())));
                    return objectMapper.convertValue(data, Map.class);
                }
            }
        } catch (Exception e) {
            log.warn("添加记忆失败 (服务可能未启动): {}", e.getMessage());
        }
        return Collections.emptyMap();
    }

    /**
     * 搜索记忆
     */
    public List<Map<String, Object>> searchMemories(TenantContext tenant, String sessionId,
                                                     String query, int topK) {
        return searchMemories(buildScope(tenant, sessionId), query, topK);
    }

    private List<Map<String, Object>> searchMemories(Map<String, Object> scope, String query, int topK) {
        if (!enabled) return Collections.emptyList();

        try {
            Map<String, Object> body = new HashMap<>();
            body.putAll(scope);
            body.put("query", query);
            body.put("top_k", topK);

            HttpHeaders headers = new HttpHeaders();
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
                    log.debug("搜索到 {} 条记忆: userId={}, query={}", memories.size(), scope.get("user_id"), query);
                    return memories;
                }
            }
        } catch (Exception e) {
            log.warn("搜索记忆失败 (服务可能未启动): {}", e.getMessage());
        }
        return Collections.emptyList();
    }

    /**
     * 获取用户所有记忆
     */
    public List<Map<String, Object>> getAllMemories(String userId) {
        if (!enabled) return Collections.emptyList();

        try {
            HttpHeaders headers = new HttpHeaders();
            HttpEntity<Void> request = new HttpEntity<>(headers);

            ResponseEntity<JsonNode> response = restTemplate().exchange(
                    serviceUrl + "/memories/" + userId,
                    HttpMethod.GET,
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
                        if (item.has("metadata") && !item.get("metadata").isNull()) {
                            memory.put("metadata", objectMapper.convertValue(item.get("metadata"), Map.class));
                        }
                        memories.add(memory);
                    }
                    return memories;
                }
            }
        } catch (Exception e) {
            log.warn("获取记忆失败 (服务可能未启动): {}", e.getMessage());
        }
        return Collections.emptyList();
    }

    /**
     * 删除记忆
     */
    public boolean deleteMemory(String memoryId) {
        if (!enabled) return false;

        try {
            HttpHeaders headers = new HttpHeaders();
            HttpEntity<Void> request = new HttpEntity<>(headers);

            ResponseEntity<JsonNode> response = restTemplate().exchange(
                    serviceUrl + "/memories/" + memoryId,
                    HttpMethod.DELETE,
                    request,
                    JsonNode.class
            );

            return response.getStatusCode().is2xxSuccessful();
        } catch (Exception e) {
            log.warn("删除记忆失败: {}", e.getMessage());
            return false;
        }
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
