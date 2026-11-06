package com.ruanzhu.doorhandle.module.model.service;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.model.entity.ModelOperationLog;
import com.ruanzhu.doorhandle.module.model.testsupport.OperationLogCopyFixture;
import java.time.LocalDateTime;
import java.util.List;
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

@EnabledIfSystemProperty(named="model.log.copy.source-config",matches=".+")
@EnabledIfSystemProperty(named="model.log.copy.target-config",matches=".+")
class ModelOperationAuditMySqlTest {
    private static final LocalDateTime LOCAL=LocalDateTime.of(2026,10,14,16,30),UTC=LOCAL.minusHours(8);
    private OperationLogCopyFixture fixture;
    private JdbcTemplate source,target;
    private ModelOperationAuditStore store;
    private TransactionTemplate tx;
    @BeforeEach void setup() throws Exception {
        fixture=new OperationLogCopyFixture("model.log.copy","doorhandle_model_verify_",true);
        source=fixture.source();target=fixture.target();store=new ModelOperationAuditStore(target,new ObjectMapper().setSerializationInclusion(JsonInclude.Include.NON_NULL));
        tx=new TransactionTemplate(new DataSourceTransactionManager(fixture.targetDataSource()));
        for(var database:List.of(source,target))for(int id:new int[]{7,8})database.update("INSERT INTO model_management(model_id,model_name,version,model_path) VALUES(?,?,?,?)",id,"fixture-"+id,"v1","fixture.onnx");
        source.update("INSERT INTO model_operation_log(id,model_id,operation_type,operator,operation_time,remark) VALUES(11,7,'PUBLISH',NULL,?,NULL)",LOCAL);
        source.update("INSERT INTO model_operation_log(id,model_id,operation_type,operator,operation_time,remark) VALUES(12,7,'','旧操作人 ',?,'保留备注 ')",LOCAL);
    }
    @AfterEach void cleanup() throws Exception {if(fixture!=null)fixture.close();}
    private void copy() throws Exception {fixture.copy("40-model-operations.sql","__SOURCE_MODEL_LOG_OFFSET__");}
    private long count(){return target.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='DETECTION_MODEL_OPERATION'",Long.class);}
    private void empty(){assertThat(count()).isZero();assertThat(source.queryForObject("SELECT COUNT(*) FROM model_operation_log",Long.class)).isEqualTo(2);}
    private ModelOperationLog event(int model,String action){var row=new ModelOperationLog();row.setModelId(model);row.setOperationType(action);row.setOperator("主管");row.setOperationTime(LOCAL);row.setRemark("操作说明");return row;}

    @Test void copyPreservesNullableSnapshotsTimeOrderingAndOriginalIdsWithoutInventingAnOwner() throws Exception {
        copy();assertThat(fixture.sourceName()).isNotEqualTo(fixture.targetName());
        var rows=store.selectByModelId(7);assertThat(rows).hasSize(2);
        assertThat(rows).extracting(ModelOperationLog::getLegacyId).containsExactly(12L,11L);
        assertThat(rows.get(0).getOperationType()).isEmpty();assertThat(rows.get(0).getOperator()).isEqualTo("旧操作人 ");
        assertThat(rows.get(0).getRemark()).isEqualTo("保留备注 ");assertThat(rows.get(1).getOperator()).isNull();assertThat(rows.get(1).getRemark()).isNull();
        assertThat(rows.get(0).getOperationTime()).isEqualTo(LOCAL);
        assertThat(target.queryForList("SELECT occurred_at FROM audit_event",LocalDateTime.class)).containsOnly(UTC);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event WHERE owner_user_id IS NOT NULL OR actor_user_id IS NOT NULL OR resource_id IS NOT NULL",Long.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='model_operation_log'",Long.class)).isZero();
    }

    @Test void modelPrimaryKeyUpdateAndDeleteKeepTheOriginalCascadeSemantics() throws Exception {
        copy();tx.executeWithoutResult(status->store.append(event(8,"PUBLISH")));
        target.update("INSERT INTO audit_event(event_id,kind,resource_type,resource_id,action,outcome,occurred_at,payload_version,payload_json) VALUES(UUID(),'INFRA_OPERATION','API','7','POST','SUCCESS',UTC_TIMESTAMP(6),1,JSON_OBJECT('operatorName','fixture','requestMethod',NULL,'requestPath',NULL,'changeSummary',NULL,'changeSummarySqlNull',CAST('true' AS JSON),'clientIp',NULL,'legacyCreatedAt',NULL))");
        target.update("UPDATE model_management SET model_id=70 WHERE model_id=7");
        assertThat(store.selectByModelId(7)).isEmpty();assertThat(store.selectByModelId(70)).hasSize(2);
        assertThat(store.selectByModelId(70)).extracting(ModelOperationLog::getModelId).containsOnly(70);
        target.update("DELETE FROM model_management WHERE model_id=70");
        assertThat(store.selectByModelId(70)).isEmpty();assertThat(store.selectByModelId(8)).hasSize(1);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='INFRA_OPERATION'",Long.class)).isEqualTo(1);
        assertThat(source.queryForObject("SELECT COUNT(*) FROM model_operation_log",Long.class)).isEqualTo(2);
    }

    @ParameterizedTest @ValueSource(strings={"missing-reference","unrelated-kind-reference","padded-kind"})
    void productionAuditReferenceTriggersRejectInvalidKindShapes(String invalid) {
        String kind="unrelated-kind-reference".equals(invalid)?"TEST_OTHER":"padded-kind".equals(invalid)?"DETECTION_MODEL_OPERATION ":"DETECTION_MODEL_OPERATION";
        Integer reference="missing-reference".equals(invalid)?null:7;
        assertThatThrownBy(()->target.update("INSERT INTO audit_event(event_id,kind,resource_type,detection_model_id,action,occurred_at,payload_version,payload_json) VALUES(UUID(),?,'DETECTION_MODEL',?,'PUBLISH',UTC_TIMESTAMP(6),1,JSON_OBJECT())",kind,reference))
                .isInstanceOf(DataAccessException.class).hasMessageContaining("Model audit reference");empty();
    }

    @Test void typedAuditRequiresTheModelTransactionAndItsFailureRollsBackTheModelChange() throws Exception {
        copy();assertThatThrownBy(()->store.append(event(7,"PUBLISH"))).isInstanceOf(IllegalStateException.class);
        target.execute("ALTER TABLE audit_event ADD CONSTRAINT fixture_reject_new_model_audit CHECK(legacy_source IS NOT NULL)");
        assertThatThrownBy(()->tx.executeWithoutResult(status->{target.update("UPDATE model_management SET status='DISABLED' WHERE model_id=7");store.append(event(7,"PUBLISH"));})).isInstanceOf(DataAccessException.class);
        assertThat(target.queryForObject("SELECT status FROM model_management WHERE model_id=7",String.class)).isEqualTo("READY");assertThat(count()).isEqualTo(2);
    }

    @Test void sameSchemaAndMissingTargetModelCannotPassCopy() {
        assertThatThrownBy(()->fixture.copy("40-model-operations.sql","__SOURCE_MODEL_LOG_OFFSET__","+08:00",fixture.targetName())).isInstanceOf(ScriptStatementFailedException.class).hasMessageContaining("DATABASE()");empty();
        target.update("DELETE FROM model_management WHERE model_id=7");
        assertThatThrownBy(this::copy).isInstanceOf(ScriptStatementFailedException.class);empty();
    }

    @ParameterizedTest @ValueSource(strings={"1960-01-01T00:00:00","9999-01-01T00:00:00"})
    void unchangedOutOfRangeTimezoneResultMustNotBeMistakenForUtc(String time) {
        source.update("UPDATE model_operation_log SET operation_time=? WHERE id=11",LocalDateTime.parse(time));
        assertThatThrownBy(this::copy).isInstanceOf(ScriptStatementFailedException.class).hasMessageContaining("TIMESTAMPDIFF");empty();
        assertThat(source.queryForObject("SELECT operation_time FROM model_operation_log WHERE id=11",LocalDateTime.class)).isEqualTo(LocalDateTime.parse(time));
    }

    @ParameterizedTest @ValueSource(strings={"+00:00","-05:30"})
    void explicitOffsetsDetermineUtcWithoutAssumingBeijing(String offset) throws Exception {
        fixture.copy("40-model-operations.sql","__SOURCE_MODEL_LOG_OFFSET__",offset,fixture.sourceName());
        assertThat(target.queryForList("SELECT occurred_at FROM audit_event",LocalDateTime.class))
                .containsOnly(LOCAL.atOffset(java.time.ZoneOffset.of(offset)).withOffsetSameInstant(java.time.ZoneOffset.UTC).toLocalDateTime());
        assertThat(store.selectByModelId(7)).extracting(ModelOperationLog::getOperationTime).containsOnly(LOCAL);
    }

    @ParameterizedTest @ValueSource(strings={"new-column","type","nullable","collation","default","index","foreign-key","cascade","check","trigger"})
    void changedSourceDeclarationsAbortWithoutOmittingFacts(String change) {
        switch(change) {
            case "new-column"->source.execute("ALTER TABLE model_operation_log ADD extra_fact VARCHAR(64) NULL");
            case "type"->source.execute("ALTER TABLE model_operation_log MODIFY remark VARCHAR(256) NULL");
            case "nullable"->source.execute("ALTER TABLE model_operation_log MODIFY operation_type VARCHAR(32) NULL");
            case "collation"->source.execute("ALTER TABLE model_operation_log MODIFY operation_type VARCHAR(32) COLLATE utf8mb4_bin NOT NULL");
            case "default"->source.execute("ALTER TABLE model_operation_log MODIFY operation_type VARCHAR(32) NOT NULL DEFAULT 'UNKNOWN'");
            case "index"->source.execute("ALTER TABLE model_operation_log DROP INDEX idx_model_operation_log_model_time");
            case "foreign-key"->source.execute("ALTER TABLE model_operation_log DROP FOREIGN KEY fk_model_operation_log_model");
            case "cascade"->{source.execute("ALTER TABLE model_operation_log DROP FOREIGN KEY fk_model_operation_log_model");source.execute("ALTER TABLE model_operation_log ADD CONSTRAINT fk_model_operation_log_model FOREIGN KEY(model_id) REFERENCES model_management(model_id) ON DELETE RESTRICT ON UPDATE CASCADE");}
            case "check"->source.execute("ALTER TABLE model_operation_log ADD CONSTRAINT extra_source_check CHECK(model_id>0)");
            case "trigger"->source.execute("CREATE TRIGGER extra_source_trigger BEFORE INSERT ON model_operation_log FOR EACH ROW SET NEW.remark=NEW.remark");
            default->throw new IllegalArgumentException(change);
        }
        assertThatThrownBy(this::copy).isInstanceOf(ScriptStatementFailedException.class);empty();
    }

    @ParameterizedTest @ValueSource(strings={"legacy-source-space","legacy-key-space","operator","timestamp","quantity-unit","policy-version","previous-sha","event-sha","message-id"})
    void equalCountsCannotHideChangedOriginalEvidence(String change) {
        String assignment=switch(change){case "legacy-source-space"->"NEW.legacy_source=CONCAT(NEW.legacy_source,' ')";case "legacy-key-space"->"NEW.legacy_key=CONCAT(NEW.legacy_key,' ')";case "operator"->"NEW.payload_json=JSON_SET(NEW.payload_json,'$.operatorName','changed')";case "timestamp"->"NEW.payload_json=JSON_REMOVE(NEW.payload_json,'$.legacyOperationTime')";case "quantity-unit"->"NEW.quantity=1,NEW.unit='TOKENS'";case "policy-version"->"NEW.policy_version='injected'";case "previous-sha"->"NEW.previous_sha256=REPEAT('a',64)";case "event-sha"->"NEW.event_sha256=REPEAT('b',64)";case "message-id"->"NEW.message_id=999";default->throw new IllegalArgumentException(change);};
        target.execute("CREATE TRIGGER corrupt_model_copy BEFORE INSERT ON audit_event FOR EACH ROW SET "+assignment);
        assertThatThrownBy(this::copy).isInstanceOf(ScriptStatementFailedException.class).hasMessageContaining("LEFT JOIN audit_event");empty();
    }

    @Test void copyCannotOverwriteExistingModelHistory() throws Exception {copy();assertThatThrownBy(this::copy).isInstanceOf(ScriptStatementFailedException.class);assertThat(count()).isEqualTo(2);}
}
