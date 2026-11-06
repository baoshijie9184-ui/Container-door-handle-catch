package com.ruanzhu.doorhandle.module.infra.service;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.workflow.AuditEvent;
import com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcAuditStore;
import com.ruanzhu.doorhandle.module.infra.entity.OperationAuditLog;
import java.time.ZoneOffset;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/** Legacy username snapshots do not establish a numeric account owner. */
@Repository
public class InfraOperationAuditStore {
    public record InfraOperationV1(String operatorName,String requestMethod,String requestPath,
            JsonNode changeSummary,boolean changeSummarySqlNull,String clientIp,String legacyCreatedAt) { }
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final JdbcAuditStore audits;
    private final TransactionTemplate tx;
    public InfraOperationAuditStore(JdbcTemplate jdbc,ObjectMapper json,PlatformTransactionManager manager) {
        this.jdbc=jdbc;this.json=json.copy().setSerializationInclusion(JsonInclude.Include.ALWAYS)
                .enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS,DeserializationFeature.USE_BIG_INTEGER_FOR_INTS);
        this.json.setNodeFactory(JsonNodeFactory.withExactBigDecimals(true));
        audits=new JdbcAuditStore(jdbc,this.json,Map.of("INFRA_OPERATION",InfraOperationV1.class));
        tx=new TransactionTemplate(manager);
    }
    public void append(OperationAuditLog log) {
        if(log==null||log.getOperator()==null||longer(log.getOperator(),64)||log.getCreatedAt()==null
                ||log.getAction()==null||log.getAction().isBlank()||longer(log.getAction(),32)
                ||log.getResourceType()==null||longer(log.getResourceType(),64)
                ||longer(log.getResourceId(),128)||log.getResult()==null||longer(log.getResult(),16)
                ||longer(log.getRequestMethod(),16)||longer(log.getClientIp(),45))
            throw new IllegalArgumentException("基础操作审计字段无效");
        final JsonNode summary;
        try {summary=log.getChangeSummary()==null?null:json.readTree(log.getChangeSummary());}
        catch(Exception malformed){throw new IllegalArgumentException("操作摘要不是完整 JSON，未截断或丢弃原摘要",malformed);}
        if(log.getChangeSummary()!=null&&summary==null)throw new IllegalArgumentException("操作摘要为空 JSON 文本");
        var payload=new InfraOperationV1(log.getOperator(),log.getRequestMethod(),log.getRequestPath(),summary,
                log.getChangeSummary()==null,log.getClientIp(),null);
        var utc=log.getCreatedAt().atOffset(ZoneOffset.ofHours(8)).withOffsetSameInstant(ZoneOffset.UTC).toLocalDateTime();
        tx.executeWithoutResult(status->{
            String event=audits.appendInfraOperation(new AuditEvent("INFRA_OPERATION",null,null,log.getResourceType(),
                    log.getResourceId(),null,null,null,null,log.getAction(),null,null,utc,1,payload),log.getResult());
            log.setId(jdbc.queryForObject("SELECT id FROM audit_event WHERE event_id=?",Long.class,event));
        });
    }
    private static boolean longer(String value,int limit){return value!=null&&value.codePointCount(0,value.length())>limit;}
}
