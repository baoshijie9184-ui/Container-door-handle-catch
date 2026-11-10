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
import com.ruanzhu.doorhandle.contracts.collaboration.ChangeHistory;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;

/** Package-private append path for an actor already authorized by the owning operation. */
final class OperationsAuditPersistence {
    record OperationV1(String scope,String domain,String result,Long resourceVersion,String legacyId,String legacyCreatedAt) {
        OperationV1 {
            OperationsAuditPersistence.scope(scope);token(domain,48);token(result,40);
            if((legacyId==null)!=(legacyCreatedAt==null))throw new IllegalArgumentException("Incomplete original audit evidence");
        }
    }
    record OperationV2(String scope,String domain,String result,Long resourceVersion,String resourceType,
            String actorUsername,String actorDisplayName,String actorRole,Long beforeVersion,
            String causationRequestId,java.util.List<ChangeHistory.Change> changes) {
        OperationV2 {
            OperationsAuditPersistence.scope(scope);token(domain,48);token(result,40);token(resourceType,64);
            if(actorUsername==null||actorUsername.isBlank()||actorUsername.length()>128
                    ||actorDisplayName!=null&&actorDisplayName.length()>128
                    ||!Set.of("SUPERVISOR","INSPECTOR").contains(actorRole)
                    ||beforeVersion!=null&&beforeVersion<0||resourceVersion!=null&&resourceVersion<0)
                throw new IllegalArgumentException("Invalid operation identity or revision");
            token(causationRequestId,128);changes=java.util.List.copyOf(changes);
            if(changes.size()>64)throw new IllegalArgumentException("Too many audit fields");
            var fields=new java.util.HashSet<String>();
            for(var change:changes) {
                token(change.field(),64);
                if(!fields.add(change.field())||change.label()==null||change.label().length()>80
                        ||!Set.of("ADD","REMOVE","REPLACE","CHANGED").contains(change.operation())
                        ||change.valueType()!=null&&change.valueType().length()>32
                        ||change.redacted()&&(change.before()!=null||change.after()!=null||!"CHANGED".equals(change.operation())))
                    throw new IllegalArgumentException("Invalid audit field change");
                scalar(change.before());scalar(change.after());
            }
        }
    }
    record Decoded(String scope,String domain,String result,Long resourceVersion,OperationV2 detail) { }
    record Appended(String eventId,String auditId,java.time.Instant occurredAt,boolean created) { }
    private final JdbcTemplate jdbc;
    private final ObjectMapper json=new ObjectMapper().enable(com.fasterxml.jackson.databind.DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES);
    private final JdbcAuditStore store;
    OperationsAuditPersistence(JdbcTemplate jdbc) {
        this.jdbc=jdbc;store=new JdbcAuditStore(jdbc,json,Map.of("OPERATIONS",OperationV1.class),
                Map.of("OPERATIONS",Map.of(1,OperationV1.class,2,OperationV2.class)));
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
    Decoded decode(int version,String value) {
        if(version==1){var old=decode(value);return new Decoded(old.scope(),old.domain(),old.result(),old.resourceVersion(),null);}
        if(version!=2)throw new IllegalStateException("Unregistered operations audit version");
        try {var item=json.readValue(value,OperationV2.class);return new Decoded(item.scope(),item.domain(),item.result(),item.resourceVersion(),item);}
        catch(JsonProcessingException error){throw new IllegalStateException("Stored operations audit payload is invalid",error);}
    }
    Appended appendChange(AgentActor actor,String scope,String domain,String action,String resource,String request,
            String result,Long version,String type,String displayName,Long before,java.util.List<ChangeHistory.Change> changes) {
        token(action,64);token(resource,160);token(request,128);
        var payload=new OperationV2(scope,domain,result,version,type,actor.username(),displayName,actor.role().name(),before,request,changes);
        try {if(json.writeValueAsBytes(payload).length>262144)throw new IllegalArgumentException("审计差异超过允许大小");}
        catch(JsonProcessingException invalid){throw new IllegalArgumentException("审计差异不可编码",invalid);}
        String eventId;boolean created=true;
        try {eventId=store.append(new AuditEvent("OPERATIONS",actor.userId(),actor.userId(),"OPERATIONS",resource,
                null,null,null,request,action,null,null,null,2,payload));}
        catch(DuplicateKeyException duplicate) {
            var rows=jdbc.queryForList("SELECT event_id,payload_version,payload_json FROM audit_event WHERE kind='OPERATIONS' AND actor_user_id=? "
                    +"AND operation_domain=? AND action=? AND resource_id=? AND request_id=? AND operation_result=? AND payload_version=2 AND operation_resource_type=? FOR SHARE",
                    actor.userId(),domain,action,resource,request,result,type);
            if(rows.size()!=1)throw duplicate;
            var row=rows.get(0);var existing=decode(((Number)row.get("payload_version")).intValue(),String.valueOf(row.get("payload_json")));
            if(!payload.equals(existing.detail()))throw new IllegalStateException("审计请求编号冲突");
            eventId=String.valueOf(row.get("event_id"));created=false;
        }
        final boolean fresh=created;
        return jdbc.queryForObject("SELECT id,event_id,occurred_at FROM audit_event WHERE event_id=?",(rs,n)->new Appended(
                rs.getString("event_id"),rs.getString("id"),rs.getObject("occurred_at",LocalDateTime.class).toInstant(ZoneOffset.UTC),fresh),eventId);
    }
    private static void scalar(Object value) {
        if(value==null||value instanceof Boolean||value instanceof Number)return;
        if(!(value instanceof String text)||text.length()>512)throw new IllegalArgumentException("Audit values must be bounded scalars");
    }
    static String token(String value,int max) {
        if(value==null || value.length()>max || !value.matches("[A-Za-z0-9_:./-]+"))throw new IllegalArgumentException("审计标识无效");
        return value;
    }
    static void scope(String value) {if(value==null || !Set.of("PRIVATE","ENTERPRISE").contains(value))throw new IllegalArgumentException("审计范围无效");}
    static LocalDateTime displayTime(LocalDateTime utc) {return utc==null?null:utc.atOffset(ZoneOffset.UTC).withOffsetSameInstant(ZoneOffset.ofHours(8)).toLocalDateTime();}
}
