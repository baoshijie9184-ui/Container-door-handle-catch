package com.ruanzhu.doorhandle.module.infra.service;

import java.util.Map;

public interface OperationAuditService {
    void recordSuccess(String resourceType, String resourceId, String action, Map<String, ?> changes);
    void recordFailure(String resourceType, String resourceId, String action, Throwable failure);
    /** HTTP completion evidence only; never reads a request body or infers business-operation success. */
    void recordHttp(String method,String path,int status,String clientIp,Throwable failure);
}
