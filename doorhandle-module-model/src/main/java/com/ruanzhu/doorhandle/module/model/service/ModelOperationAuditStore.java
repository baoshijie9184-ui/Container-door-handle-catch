package com.ruanzhu.doorhandle.module.model.service;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.workflow.AuditEvent;
import com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcAuditStore;
import com.ruanzhu.doorhandle.module.model.entity.ModelOperationLog;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** The model FK preserves the original UPDATE/DELETE CASCADE behavior; no guessed account ownership. */
@Repository
public class ModelOperationAuditStore {
    public record ModelOperationV1(String operatorName,String remark,String legacyOperationTime) { }
    private static final ZoneOffset BUSINESS_OFFSET=ZoneOffset.ofHours(8);
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final JdbcAuditStore audits;

    public ModelOperationAuditStore(JdbcTemplate jdbc,ObjectMapper json) {
        this.jdbc=jdbc;
        // The HTTP mapper omits nulls; this persisted protocol requires explicit nullable fields.
        this.json=json.copy().setSerializationInclusion(JsonInclude.Include.ALWAYS)
                .enable(DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES);
        audits=new JdbcAuditStore(jdbc,this.json,Map.of("DETECTION_MODEL_OPERATION",ModelOperationV1.class));
    }

    /** Caller owns the model mutation transaction; failure must roll back the model and its audit together. */
    public void append(ModelOperationLog log) {
        if(log==null||log.getModelId()==null||log.getOperationTime()==null||log.getOperationType()==null
                ||log.getOperationType().isBlank()||longer(log.getOperationType(),32)
                ||longer(log.getOperator(),64)||longer(log.getRemark(),255))
            throw new IllegalArgumentException("模型操作审计字段无效");
        LocalDateTime utc=log.getOperationTime().atOffset(BUSINESS_OFFSET).withOffsetSameInstant(ZoneOffset.UTC).toLocalDateTime();
        String event=audits.appendDetectionModelOperation(new AuditEvent("DETECTION_MODEL_OPERATION",null,null,
                "DETECTION_MODEL",null,null,null,null,null,log.getOperationType(),null,null,utc,1,
                new ModelOperationV1(log.getOperator(),log.getRemark(),null)),log.getModelId());
        log.setId(jdbc.queryForObject("SELECT id FROM audit_event WHERE event_id=?",Long.class,event));
    }

    /** Preserve the prior newest-first order. Original IDs remain separately available after cursor remapping. */
    public List<ModelOperationLog> selectByModelId(Integer modelId) {
        return jdbc.query("""
                SELECT id,detection_model_id,action,occurred_at,payload_version,payload_json,legacy_source,legacy_key
                FROM audit_event WHERE kind='DETECTION_MODEL_OPERATION' AND detection_model_id=?
                ORDER BY occurred_at DESC,id DESC
                """,(row,index)->{
            if(row.getInt("payload_version")!=1)throw new IllegalStateException("不支持的模型操作审计版本");
            ModelOperationV1 body;
            try {body=json.readValue(row.getString("payload_json"),ModelOperationV1.class);}
            catch(Exception malformed){throw new IllegalStateException("模型操作审计内容无法读取",malformed);}
            var result=new ModelOperationLog();result.setId(row.getLong("id"));result.setModelId(row.getInt("detection_model_id"));
            result.setOperationType(row.getString("action"));result.setOperator(body.operatorName());result.setRemark(body.remark());
            if(body.legacyOperationTime()!=null)result.setOperationTime(LocalDateTime.parse(body.legacyOperationTime()));
            else result.setOperationTime(row.getObject("occurred_at",LocalDateTime.class).atOffset(ZoneOffset.UTC).withOffsetSameInstant(BUSINESS_OFFSET).toLocalDateTime());
            if("model_operation_log".equals(row.getString("legacy_source")))result.setLegacyId(Long.valueOf(row.getString("legacy_key")));
            return result;
        },modelId);
    }
    private static boolean longer(String value,int limit){return value!=null&&value.codePointCount(0,value.length())>limit;}
}
