package com.ruanzhu.doorhandle.module.infra.service;

import java.util.Map;

public interface OperationAuditService {
    void recordSuccess(String resourceType, String resourceId, String action, Map<String, ?> changes);
    void recordFailure(String resourceType, String resourceId, String action, Throwable failure);
}
