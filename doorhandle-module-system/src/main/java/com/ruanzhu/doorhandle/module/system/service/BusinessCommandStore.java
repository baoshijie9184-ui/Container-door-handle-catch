package com.ruanzhu.doorhandle.module.system.service;

import com.fasterxml.jackson.databind.*;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.framework.persistence.JdbcTransactions;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import java.lang.reflect.Type;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** One owned request, content digest and exact result, committed atomically with the domain change. */
final class BusinessCommandStore {
    record Payload(String domain,String action) { }
    record Claim(String id,boolean repeated,String result) { }
    record Receipt(String resourceVersion,String auditId,String eventId) { }
    record ResultV1(JsonNode result,Receipt receipt) { }
    private final JdbcTemplate jdbc;
    private final ObjectMapper json=new ObjectMapper().findAndRegisterModules()
            .enable(MapperFeature.SORT_PROPERTIES_ALPHABETICALLY).enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS)
            .enable(DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES);
    BusinessCommandStore(JdbcTemplate jdbc){this.jdbc=jdbc;}
    String digest(String method,String domain,String action,Long expected,Object input){return sha(write(Arrays.asList(method,domain,action,expected,input)));}
    Claim claim(long actor,String request,String digest,String domain,String action) {
        JdbcTransactions.requireActive(jdbc);String id=UUID.randomUUID().toString();
        try {jdbc.update("""
            INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,
                owner_user_id,actor_user_id,resource_type,status,payload_version,payload_json)
            VALUES(?,'BUSINESS_COMMAND',?,?,?,?,?,'BUSINESS_COMMAND','STARTED',1,?)
            """,id,"OWNER:"+actor,request,digest,actor,actor,write(new Payload(domain,action)));
            return new Claim(id,false,null);
        }catch(DuplicateKeyException duplicate){
            var rows=jdbc.queryForList("SELECT workflow_id,request_sha256,status,result_version,result_json,result_sha256,payload_json FROM workflow_instance "
                    +"WHERE kind='BUSINESS_COMMAND' AND idempotency_scope=? AND request_id=? FOR UPDATE","OWNER:"+actor,request);
            if(rows.size()!=1)throw duplicate;var row=rows.get(0);
            if(!digest.equals(row.get("request_sha256")))throw new BusinessException(409,"请求编号已用于不同内容，请重新确认后使用新编号");
            try {if(!new Payload(domain,action).equals(json.readValue(String.valueOf(row.get("payload_json")),Payload.class)))throw new IllegalStateException("命令身份不一致");}
            catch(com.fasterxml.jackson.core.JsonProcessingException invalid){throw new IllegalStateException("命令载荷无效",invalid);}
            String body=(String)row.get("result_json");
            if(!"SUCCEEDED".equals(row.get("status"))||!Objects.equals(1,((Number)row.get("result_version")).intValue())||body==null||!sha(body).equals(row.get("result_sha256")))
                throw new BusinessException(409,"请求结果尚未确认，禁止重复执行");
            return new Claim(String.valueOf(row.get("workflow_id")),true,body);
        }
    }
    void complete(Claim claim,Object result,Receipt receipt) {
        String body=write(new ResultV1(json.valueToTree(result),receipt));if(body.getBytes(StandardCharsets.UTF_8).length>2097152)throw new IllegalStateException("命令结果超过允许大小");
        if(jdbc.update("UPDATE workflow_instance SET status='SUCCEEDED',revision=revision+1,result_version=1,result_json=?,result_sha256=?,updated_at=UTC_TIMESTAMP(6),finished_at=UTC_TIMESTAMP(6) WHERE workflow_id=? AND kind='BUSINESS_COMMAND' AND status='STARTED' AND revision=0",
                body,sha(body),claim.id())!=1)throw new IllegalStateException("业务命令回执写入失败");
    }
    Object replay(Claim claim,Type type){try{
        var stored=json.readValue(claim.result(),ResultV1.class);headers(stored.receipt());
        return type==Void.TYPE?null:json.readValue(stored.result().toString(),json.getTypeFactory().constructType(type));
    }catch(com.fasterxml.jackson.core.JsonProcessingException invalid){throw new IllegalStateException("命令回执解码失败",invalid);}}
    Receipt receipt(long actor,String request,String resourceType,String resourceId,Long version){
        var rows=jdbc.queryForList("SELECT id,event_id FROM audit_event WHERE kind='OPERATIONS' AND actor_user_id=? AND request_id=? AND operation_resource_type=? AND resource_id=? ORDER BY id LIMIT 1",actor,request,resourceType,resourceId);
        var row=rows.isEmpty()?null:rows.get(0);return new Receipt(version==null?null:version.toString(),row==null?null:String.valueOf(row.get("id")),row==null?null:String.valueOf(row.get("event_id")));
    }
    static void headers(Receipt receipt){
        if(receipt==null)return;var attributes=org.springframework.web.context.request.RequestContextHolder.getRequestAttributes();
        if(attributes instanceof org.springframework.web.context.request.ServletRequestAttributes servlet&&servlet.getResponse()!=null){
            if(receipt.resourceVersion()!=null)servlet.getResponse().setHeader("X-Resource-Version",receipt.resourceVersion());
            if(receipt.auditId()!=null)servlet.getResponse().setHeader("X-Audit-ID",receipt.auditId());
            if(receipt.eventId()!=null)servlet.getResponse().setHeader("X-Change-Event-ID",receipt.eventId());
        }
    }
    private String write(Object value){try{return json.writeValueAsString(value);}catch(com.fasterxml.jackson.core.JsonProcessingException invalid){throw new IllegalArgumentException("无法计算业务命令摘要",invalid);}}
    private static String sha(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(java.security.NoSuchAlgorithmException impossible){throw new IllegalStateException(impossible);}}
}
