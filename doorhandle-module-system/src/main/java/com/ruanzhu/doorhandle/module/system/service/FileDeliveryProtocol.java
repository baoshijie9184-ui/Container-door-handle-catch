package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.framework.persistence.workflow.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Map;
import java.util.Set;

final class FileDeliveryProtocol {
    static final Set<String> TERMINAL=Set.of("SERVER_COMPLETED","HEAD_COMPLETED","INTERRUPTED","REDIRECT_AUTHORIZED");
    record DeliveryV1(String scope,String domain,String fileId,String correlationId,Long resourceVersion,Long expectedBytes,
            long acceptedBytesLowerBound,Integer httpStatus,String deliveryMode,String legacyId,String legacyCreatedAt,String legacyUpdatedAt) {
        DeliveryV1 {
            OperationsAuditPersistence.scope(scope);OperationsAuditPersistence.token(domain,48);OperationsAuditPersistence.token(correlationId,128);
            if(fileId!=null)OperationsAuditPersistence.token(fileId,128);
            if(expectedBytes!=null && expectedBytes<0 || acceptedBytesLowerBound<0 || httpStatus!=null && (httpStatus<100 || httpStatus>599)
                    || deliveryMode==null || !Set.of("BODY","HEAD","REDIRECT","UNKNOWN").contains(deliveryMode))throw new IllegalArgumentException("交付证据无效");
            if((legacyId==null)!=(legacyCreatedAt==null) || (legacyId==null)!=(legacyUpdatedAt==null))throw new IllegalArgumentException("Incomplete original delivery evidence");
        }
        DeliveryV1 observed(long lowerBound,Integer status,String mode) {
            return new DeliveryV1(scope,domain,fileId,correlationId,resourceVersion,expectedBytes,Math.max(acceptedBytesLowerBound,lowerBound),status,
                    mode,legacyId,legacyCreatedAt,legacyUpdatedAt);
        }
    }
    static WorkflowProtocols protocols() {
        return WorkflowProtocols.defaults().with(new WorkflowProtocol<>(WorkflowKind.FILE_DELIVERY,1,DeliveryV1.class,
                Set.of("AUTHORIZED","HEAD_AUTHORIZED","REDIRECT_AUTHORIZED"),TERMINAL,
                Map.of("AUTHORIZED",Set.of("STREAMING","SERVER_COMPLETED","INTERRUPTED","UNKNOWN"),
                        "HEAD_AUTHORIZED",Set.of("HEAD_COMPLETED","INTERRUPTED","UNKNOWN"),
                        "STREAMING",Set.of("SERVER_COMPLETED","INTERRUPTED","UNKNOWN"),
                        "UNKNOWN",Set.of("STREAMING","SERVER_COMPLETED","HEAD_COMPLETED","INTERRUPTED","UNKNOWN")),value->{},false));
    }
    /** The delimiter and null marker cannot occur in validated tokens; migration SQL uses the same encoding. */
    static String digest(long actor,String resource,DeliveryV1 value) {
        var text=String.join("\n",Long.toString(actor),value.scope(),value.domain(),resource,part(value.fileId()),value.correlationId(),
                part(value.resourceVersion()),part(value.expectedBytes()),value.deliveryMode());
        try {return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8)));}
        catch(java.security.NoSuchAlgorithmException impossible) {throw new IllegalStateException(impossible);}
    }
    private static String part(Object value) {return value==null?"~":value.toString();}
}
