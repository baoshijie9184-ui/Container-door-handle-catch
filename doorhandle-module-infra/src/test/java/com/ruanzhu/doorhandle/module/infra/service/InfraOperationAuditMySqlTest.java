package com.ruanzhu.doorhandle.module.infra.service;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.infra.entity.OperationAuditLog;
import com.ruanzhu.doorhandle.module.infra.service.impl.OperationAuditServiceImpl;
import com.ruanzhu.doorhandle.module.infra.testsupport.OperationLogCopyFixture;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.init.ScriptStatementFailedException;
import org.springframework.transaction.support.TransactionTemplate;
import static org.assertj.core.api.Assertions.*;

@EnabledIfSystemProperty(named="infra.log.copy.source-config",matches=".+")
@EnabledIfSystemProperty(named="infra.log.copy.target-config",matches=".+")
class InfraOperationAuditMySqlTest {
    private static final LocalDateTime LOCAL=LocalDateTime.of(2026,10,14,16,30),UTC=LOCAL.minusHours(8);
    private OperationLogCopyFixture fixture;
    private JdbcTemplate source,target;
    private InfraOperationAuditStore store;
    private DataSourceTransactionManager manager;
    @BeforeEach void setup() throws Exception {
        fixture=new OperationLogCopyFixture("infra.log.copy","doorhandle_feature_",false);
        source=fixture.source();target=fixture.target();manager=new DataSourceTransactionManager(fixture.targetDataSource());
        store=new InfraOperationAuditStore(target,new ObjectMapper().setSerializationInclusion(JsonInclude.Include.NON_NULL),manager);
        source.update("INSERT INTO operation_audit_log(id,operator,action,resource_type,resource_id,request_method,request_path,change_summary,result,client_ip,created_at) VALUES(101,'system','','API',NULL,NULL,NULL,NULL,'',NULL,?)",LOCAL);
        source.update("INSERT INTO operation_audit_log(id,operator,action,resource_type,resource_id,request_method,request_path,change_summary,result,client_ip,created_at) VALUES(102,'审核人 ','POST','API','/api/a','POST','/api/a',CAST('null' AS JSON),'FAILURE','::1',?)",LOCAL);
        source.update("INSERT INTO operation_audit_log(id,operator,action,resource_type,resource_id,request_method,request_path,change_summary,result,client_ip,created_at) VALUES(103,'审核人','PATCH',?,NULL,'PATCH','/api/完整请求',CAST(? AS JSON),'CUSTOM_RESULT','127.0.0.1',?)","类".repeat(64),"{\"error\":\"OriginalFailure\",\"status\":409,\"request\":{\"count\":18446744073709551615,\"text\":\"原始 摘要 \"}}",LOCAL);
        source.update("INSERT INTO operation_audit_log(id,operator,action,resource_type,change_summary,result,created_at) VALUES(104,'system','POST','API',CAST('[1,true,null,\"字符串\"]' AS JSON),'SUCCESS',?)",LOCAL);
    }
    @AfterEach void cleanup() throws Exception {if(fixture!=null)fixture.close();}
    private void copy() throws Exception {fixture.copy("41-infra-operations.sql","__SOURCE_INFRA_LOG_OFFSET__");}
    private long count(){return target.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='INFRA_OPERATION'",Long.class);}
    private void empty(){assertThat(count()).isZero();assertThat(source.queryForObject("SELECT COUNT(*) FROM operation_audit_log",Long.class)).isEqualTo(4);}

    @Test void sourceNullKindsCompleteJsonWideResourceAndOriginalTimestampsArePreserved() throws Exception {
        copy();assertThat(fixture.sourceName()).isNotEqualTo(fixture.targetName());assertThat(count()).isEqualTo(4);
        assertThat(target.queryForObject("SELECT JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.changeSummarySqlNull')) FROM audit_event WHERE legacy_key='101'",String.class)).isEqualTo("true");
        assertThat(target.queryForObject("SELECT JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.changeSummarySqlNull')) FROM audit_event WHERE legacy_key='102'",String.class)).isEqualTo("false");
        for(long id:new long[]{102,103,104})assertThat(target.queryForObject("SELECT CAST(JSON_EXTRACT(payload_json,'$.changeSummary') AS CHAR) FROM audit_event WHERE legacy_key=?",String.class,Long.toString(id)))
                .isEqualTo(source.queryForObject("SELECT CAST(change_summary AS CHAR) FROM operation_audit_log WHERE id=?",String.class,id));
        assertThat(target.queryForObject("SELECT resource_type FROM audit_event WHERE legacy_key='103'",String.class)).isEqualTo("类".repeat(64));
        assertThat(target.queryForObject("SELECT outcome FROM audit_event WHERE legacy_key='103'",String.class)).isEqualTo("CUSTOM_RESULT");
        assertThat(target.queryForObject("SELECT JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.operatorName')) FROM audit_event WHERE legacy_key='102'",String.class)).isEqualTo("审核人 ");
        assertThat(target.queryForList("SELECT occurred_at FROM audit_event",LocalDateTime.class)).containsOnly(UTC);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event WHERE owner_user_id IS NOT NULL OR actor_user_id IS NOT NULL OR request_id IS NOT NULL",Long.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='operation_audit_log'",Long.class)).isZero();
    }

    @Test void runtimePreservesFailedHttpSnapshotAndCompleteNativeJsonSummary() {
        var service=new OperationAuditServiceImpl(store,new ObjectMapper());
        service.recordHttp("PATCH","/api/"+"long-path".repeat(70),422,"::1",new IllegalArgumentException("private value"));
        var row=target.queryForMap("SELECT * FROM audit_event WHERE kind='INFRA_OPERATION'");
        assertThat(row).containsEntry("owner_user_id",null).containsEntry("actor_user_id",null).containsEntry("resource_id",null).containsEntry("outcome","FAILURE");
        String payload=(String)row.get("payload_json");assertThat(payload).contains("IllegalArgumentException","422","long-path").doesNotContain("private value");
        assertThat(target.queryForObject("SELECT JSON_CONTAINS_PATH(payload_json,'one','$.legacyCreatedAt') FROM audit_event",Integer.class)).isEqualTo(1);
        assertThat(target.queryForObject("SELECT JSON_TYPE(JSON_EXTRACT(payload_json,'$.legacyCreatedAt')) FROM audit_event",String.class)).isEqualTo("NULL");
        service.recordSuccess("API","12","POST",Map.of("amount",new BigDecimal("12345678901234567890.12345678901234567890"),"note","n".repeat(9000)));
        String nativeJsonNumber=target.queryForObject("SELECT JSON_UNQUOTE(JSON_EXTRACT(CAST(? AS JSON),'$.amount'))",String.class,"{\"amount\":12345678901234567890.12345678901234567890}");
        assertThat(target.queryForObject("SELECT JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.changeSummary.amount')) FROM audit_event WHERE resource_id='12'",String.class)).isEqualTo(nativeJsonNumber);
        assertThat(target.queryForObject("SELECT CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.changeSummary.note'))) FROM audit_event WHERE resource_id='12'",Integer.class)).isEqualTo(9000);
    }

    @Test void malformedJsonIsNotSilentlyDroppedAndOuterTransactionRollbackIncludesItsAudit() {
        var row=new OperationAuditLog();row.setOperator("system");row.setAction("POST");row.setResourceType("API");row.setResult("SUCCESS");row.setCreatedAt(LOCAL);row.setChangeSummary("{broken");
        assertThatThrownBy(()->store.append(row)).isInstanceOf(IllegalArgumentException.class);empty();
        row.setChangeSummary("{\"original\":true}");
        new TransactionTemplate(manager).executeWithoutResult(status->{store.append(row);status.setRollbackOnly();});empty();
        target.execute("ALTER TABLE audit_event ADD CONSTRAINT reject_infra CHECK(kind<>'INFRA_OPERATION')");
        assertThatThrownBy(()->store.append(row)).isInstanceOf(DataAccessException.class);empty();
    }

    @Test void sameSchemaAndInvalidOffsetAreRejectedBeforeCopy() {
        assertThatThrownBy(()->fixture.copy("41-infra-operations.sql","__SOURCE_INFRA_LOG_OFFSET__","+08:00",fixture.targetName())).isInstanceOf(ScriptStatementFailedException.class).hasMessageContaining("DATABASE()");empty();
        assertThatThrownBy(()->fixture.copy("41-infra-operations.sql","__SOURCE_INFRA_LOG_OFFSET__","invalid-offset",fixture.sourceName())).isInstanceOf(ScriptStatementFailedException.class);empty();
    }

    @ParameterizedTest @ValueSource(strings={"1960-01-01T00:00:00","9999-01-01T00:00:00"})
    void outOfRangeTimezoneConversionCannotSilentlyKeepTheOriginalLocalTime(String time) {
        source.update("UPDATE operation_audit_log SET created_at=? WHERE id=101",LocalDateTime.parse(time));
        assertThatThrownBy(this::copy).isInstanceOf(ScriptStatementFailedException.class).hasMessageContaining("TIMESTAMPDIFF");empty();
        assertThat(source.queryForObject("SELECT created_at FROM operation_audit_log WHERE id=101",LocalDateTime.class)).isEqualTo(LocalDateTime.parse(time));
    }

    @ParameterizedTest @ValueSource(strings={"+00:00","-05:30"})
    void explicitSourceOffsetControlsAllCopiedTimes(String offset) throws Exception {
        fixture.copy("41-infra-operations.sql","__SOURCE_INFRA_LOG_OFFSET__",offset,fixture.sourceName());
        assertThat(target.queryForList("SELECT occurred_at FROM audit_event",LocalDateTime.class))
                .containsOnly(LOCAL.atOffset(java.time.ZoneOffset.of(offset)).withOffsetSameInstant(java.time.ZoneOffset.UTC).toLocalDateTime());
        assertThat(target.queryForObject("SELECT JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.legacyCreatedAt')) FROM audit_event WHERE legacy_key='101'",String.class)).isEqualTo("2026-10-14T16:30:00");
    }

    @ParameterizedTest @ValueSource(strings={"new-column","type","nullable","collation","default","index","check","trigger"})
    void unknownSourceStructureMustBeExplainedBeforeMigration(String change) {
        switch(change) {
            case "new-column"->source.execute("ALTER TABLE operation_audit_log ADD unseen_request_fact VARCHAR(128) NULL");
            case "type"->source.execute("ALTER TABLE operation_audit_log MODIFY request_path VARCHAR(513) NULL");
            case "nullable"->source.execute("ALTER TABLE operation_audit_log MODIFY operator VARCHAR(64) NULL");
            case "collation"->source.execute("ALTER TABLE operation_audit_log MODIFY operator VARCHAR(64) COLLATE utf8mb4_bin NOT NULL");
            case "default"->source.execute("ALTER TABLE operation_audit_log MODIFY operator VARCHAR(64) NOT NULL DEFAULT 'unknown'");
            case "index"->source.execute("ALTER TABLE operation_audit_log DROP INDEX idx_audit_resource_time");
            case "check"->source.execute("ALTER TABLE operation_audit_log ADD CONSTRAINT unseen_check CHECK(id>0)");
            case "trigger"->source.execute("CREATE TRIGGER unseen_trigger BEFORE INSERT ON operation_audit_log FOR EACH ROW SET NEW.result=NEW.result");
            default->throw new IllegalArgumentException(change);
        }
        assertThatThrownBy(this::copy).isInstanceOf(ScriptStatementFailedException.class);empty();
    }

    @ParameterizedTest @ValueSource(strings={"legacy-source-space","legacy-key-space","missing-summary","null-meaning","timestamp","quantity-unit","policy-version","previous-sha","event-sha","message-id"})
    void exactReceiptReconciliationDetectsChangesEvenWhenRowCountsMatch(String change) {
        String assignment=switch(change){case "legacy-source-space"->"NEW.legacy_source=CONCAT(NEW.legacy_source,' ')";case "legacy-key-space"->"NEW.legacy_key=CONCAT(NEW.legacy_key,' ')";case "missing-summary"->"NEW.payload_json=JSON_REMOVE(NEW.payload_json,'$.changeSummary')";case "null-meaning"->"NEW.payload_json=JSON_SET(NEW.payload_json,'$.changeSummarySqlNull',CAST('false' AS JSON))";case "timestamp"->"NEW.payload_json=JSON_REMOVE(NEW.payload_json,'$.legacyCreatedAt')";case "quantity-unit"->"NEW.quantity=1,NEW.unit='TOKENS'";case "policy-version"->"NEW.policy_version='injected'";case "previous-sha"->"NEW.previous_sha256=REPEAT('a',64)";case "event-sha"->"NEW.event_sha256=REPEAT('b',64)";case "message-id"->"NEW.message_id=999";default->throw new IllegalArgumentException(change);};
        target.execute("CREATE TRIGGER corrupt_infra_copy BEFORE INSERT ON audit_event FOR EACH ROW SET "+assignment);
        assertThatThrownBy(this::copy).isInstanceOf(ScriptStatementFailedException.class).hasMessageContaining("LEFT JOIN audit_event");empty();
    }

    @Test void secondCopyCannotReplaceExistingAuditEvidence() throws Exception {copy();assertThatThrownBy(this::copy).isInstanceOf(ScriptStatementFailedException.class);assertThat(count()).isEqualTo(4);}
}
