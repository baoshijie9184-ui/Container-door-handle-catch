package com.ruanzhu.doorhandle.module.system.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.workflow.AuditEvent;
import com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcAuditStore;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/** Package-private append path for an actor already authorized by the owning operation. */
final class OperationsAuditPersistence {
    record OperationV1(String scope,String domain,String result,Long resourceVersion,String legacyId,String legacyCreatedAt) {
        OperationV1 {
            OperationsAuditPersistence.scope(scope);token(domain,48);token(result,40);
            if((legacyId==null)!=(legacyCreatedAt==null))throw new IllegalArgumentException("Incomplete original audit evidence");
        }
    }
    private final JdbcTemplate jdbc;
    private final ObjectMapper json=new ObjectMapper().enable(com.fasterxml.jackson.databind.DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES);
    private final JdbcAuditStore store;
    OperationsAuditPersistence(JdbcTemplate jdbc) {
        this.jdbc=jdbc;store=new JdbcAuditStore(jdbc,json,Map.of("OPERATIONS",OperationV1.class));
    }
    void append(long actor,String scope,String domain,String action,String resource,String request,String result,Long version) {
        if(actor<=0)throw new IllegalArgumentException("审计账号无效");
        token(action,64);token(resource,160);token(request,128);
        var payload=new OperationV1(scope,domain,result,version,null,null);
        try {
            store.append(new AuditEvent("OPERATIONS",actor,actor,"OPERATIONS",resource,null,null,null,request,
                    action,null,null,null,1,payload));
        } catch(DuplicateKeyException duplicate) {
            var rows=jdbc.queryForList("SELECT payload_json FROM audit_event WHERE kind='OPERATIONS' AND actor_user_id=? "
                    + "AND operation_domain=? AND action=? AND resource_id=? AND request_id=? AND operation_result=? FOR SHARE",
                    actor,domain,action,resource,request,result);
            if(rows.size()!=1)throw duplicate;
            var existing=decode(String.valueOf(rows.get(0).get("payload_json")));
            if(!scope.equals(existing.scope()) || !Objects.equals(version,existing.resourceVersion()))throw new IllegalStateException("审计请求编号冲突");
        }
    }
    OperationV1 decode(String value) {
        try {return json.readValue(value,OperationV1.class);}
        catch(JsonProcessingException error) {throw new IllegalStateException("Stored operations audit payload is invalid",error);}
    }
    static String token(String value,int max) {
        if(value==null || value.length()>max || !value.matches("[A-Za-z0-9_:./-]+"))throw new IllegalArgumentException("审计标识无效");
        return value;
    }
    static void scope(String value) {if(value==null || !Set.of("PRIVATE","ENTERPRISE").contains(value))throw new IllegalArgumentException("审计范围无效");}
    static LocalDateTime displayTime(LocalDateTime utc) {return utc==null?null:utc.atOffset(ZoneOffset.UTC).withOffsetSameInstant(ZoneOffset.ofHours(8)).toLocalDateTime();}
}
