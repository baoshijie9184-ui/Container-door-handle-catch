package com.ruanzhu.doorhandle.module.infra.service.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.infra.entity.OperationAuditLog;
import com.ruanzhu.doorhandle.module.infra.service.InfraOperationAuditStore;
import com.ruanzhu.doorhandle.module.infra.service.OperationAuditService;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

@Service
@RequiredArgsConstructor
public class OperationAuditServiceImpl implements OperationAuditService {
    private static final Set<String> SENSITIVE_PARTS = Set.of(
            "password", "token", "authorization", "cookie", "secret", "accesskey");
    private final InfraOperationAuditStore store;
    private final ObjectMapper objectMapper;

    @Override
    public void recordSuccess(String resourceType, String resourceId, String action, Map<String, ?> changes) {
        persist(resourceType, resourceId, action, "SUCCESS", sanitize(changes));
    }

    @Override
    public void recordFailure(String resourceType, String resourceId, String action, Throwable failure) {
        persist(resourceType, resourceId, action, "FAILURE",
                Map.of("error", failure == null ? "unknown" : failure.getClass().getSimpleName()));
    }

    @Override
    public void recordHttp(String method,String path,int status,String clientIp,Throwable failure) {
        Map<String,Object> summary=new LinkedHashMap<>();
        summary.put("method",method);summary.put("path",path);summary.put("status",status);
        if(failure!=null)summary.put("error",failure.getClass().getSimpleName());
        else if(status>=400)summary.put("error","HTTP_STATUS");
        var log=entry("API",path!=null&&path.codePointCount(0,path.length())<=128?path:null,method,
                failure==null&&status<400?"SUCCESS":"FAILURE",summary);
        log.setRequestMethod(method);log.setRequestPath(path);log.setClientIp(clientIp);
        store.append(log);
    }

    private void persist(String resourceType, String resourceId, String action,
                         String result, Map<String, ?> summary) {
        store.append(entry(resourceType,resourceId,action,result,summary));
    }

    private OperationAuditLog entry(String resourceType,String resourceId,String action,String result,Map<String,?> summary) {
        OperationAuditLog log = new OperationAuditLog();
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        log.setOperator(authentication == null ? "system" : authentication.getName());
        log.setResourceType(resourceType);
        log.setResourceId(resourceId);
        log.setAction(action);
        log.setResult(result);
        log.setChangeSummary(toJson(summary));
        log.setCreatedAt(LocalDateTime.now(java.time.ZoneOffset.ofHours(8)));
        return log;
    }

    private Map<String, Object> sanitize(Map<String, ?> changes) {
        Map<String, Object> sanitized = new LinkedHashMap<>();
        if (changes == null) {
            return sanitized;
        }
        changes.forEach((key, value) -> sanitized.put(key, isSensitive(key) ? "[REDACTED]" : value));
        return sanitized;
    }

    private boolean isSensitive(String key) {
        String normalized = key == null ? "" : key.replace("_", "").toLowerCase(Locale.ROOT);
        return SENSITIVE_PARTS.stream().anyMatch(normalized::contains);
    }

    private String toJson(Map<String, ?> summary) {
        try {
            // A substring can turn a valid JSON snapshot into invalid/truncated evidence.
            return objectMapper.writeValueAsString(summary);
        } catch (JsonProcessingException e) {
            return "{\"serializationError\":true}";
        }
    }
}
