package com.ruanzhu.doorhandle.module.ai.model;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.testsupport.ModelBudgetMigrationFixture;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Executes the real V64 and copy38 SQL only in two pre-provisioned, independently admitted ECS schemas. */
@EnabledIfSystemProperty(named="doorhandle.model-budget.source.config",matches=".+")
class ModelBudgetMigrationMySqlTest {
    static final String A="dashscope:qwen-legacy-a", B="dashscope:qwen-legacy-unlimited",
            C="dashscope:qwen-legacy-failed", D="dashscope:qwen-legacy-empty";
    static final LocalDateTime START=LocalDateTime.parse("2026-01-02T03:04:05.123456"),
            FINISH=LocalDateTime.parse("2026-01-02T03:05:06.654321");
    static final String ORIGINAL_HASH="f".repeat(64), NOTE="  原供应商余额\n保留空白  ";
    ModelBudgetMigrationFixture fixture;JdbcTemplate source,target;TransactionTemplate tx;
    final ObjectMapper json=new ObjectMapper().enable(DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES);

    @BeforeEach void start() throws Exception {
        fixture=new ModelBudgetMigrationFixture();source=fixture.source();target=fixture.target();
        tx=new TransactionTemplate(new DataSourceTransactionManager(fixture.targetDataSource()));
        tx.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
    }
    @AfterEach void close() throws Exception {if(fixture!=null)fixture.close();}

    private void seed() {
        target.update("INSERT INTO users(id,username,password) VALUES(3,'migration-owner','fixture')");
        target.update("INSERT INTO llm_quota(scope_type,owner_user_id,model_id,period_key,total_tokens,created_at,updated_at) VALUES('USER',3,?,'TOTAL',777,?,?)",A,START,START);
        source.update("INSERT INTO agent_model_budget VALUES(?,1000,73,TRUE,NULL,7,999,?),(?,NULL,51,FALSE,NULL,0,NULL,?),(?,1000,80,TRUE,NULL,1,999,?),(?,88,99,FALSE,?,2,NULL,?)",A,START,B,START,C,START,D,FINISH,START);
        attempt(11,"Completed-MixedCase",A,"COMPLETED",20L,5L,4L,FINISH);
        attempt(12,"failed-partial",A,"FAILED",7L,null,null,FINISH);
        attempt(13,"started-unknown",A,"STARTED",null,null,null,null);
        attempt(14,"cancelled-values",A,"CANCELLED",0L,2L,0L,FINISH);
        attempt(15,"completed-no-finish",A,"COMPLETED",1L,1L,null,null);
        attempt(16,"unlimited-started",B,"STARTED",null,null,null,null);
        attempt(17,"failed-values",C,"FAILED",3L,4L,1L,FINISH);
        attempt(18,"model-case-alias",A.replace("qwen","QWEN"),"COMPLETED",1L,1L,null,FINISH);
        // The old actor no longer exists in users. This remains valid historical evidence.
        source.update("INSERT INTO agent_model_budget_observation VALUES(21,?,123,?,?,999,'Original-Request-Case',?,?)",A,START,NOTE,ORIGINAL_HASH,FINISH);
        source.update("INSERT INTO agent_model_budget_audit VALUES(31,?,999,'POLICY',-2,CAST(? AS JSON),?)",A,"{\"note\":\"原值 保留\",\"nullable\":null,\"limit\":1000}",FINISH);
    }
    private void attempt(long id,String request,String model,String status,Long input,Long output,Long cached,LocalDateTime finish) {
        source.update("INSERT INTO agent_model_budget_attempt VALUES(?,?,?,?,?,?,?,?,?)",id,request,model,status,input,output,cached,START,finish);
    }
    private long count(String table) {return target.queryForObject("SELECT COUNT(*) FROM "+table,Long.class);}
    private Map<String,Object> account(String model) {return target.queryForMap("SELECT * FROM llm_quota WHERE scope_type='MODEL' AND model_id=?",model);}
    private Map<String,List<Map<String,Object>>> sourceSnapshot() {
        return Map.of("policy",source.queryForList("SELECT * FROM agent_model_budget ORDER BY model_id"),
                "attempt",source.queryForList("SELECT * FROM agent_model_budget_attempt ORDER BY id"),
                "observation",source.queryForList("SELECT * FROM agent_model_budget_observation ORDER BY id"),
                "audit",source.queryForList("SELECT * FROM agent_model_budget_audit ORDER BY id"));
    }
    private void assertNoImport() {
        assertThat(target.queryForObject("SELECT COUNT(*) FROM llm_quota WHERE scope_type='MODEL'",Long.class)).isZero();
        assertThat(count("audit_event")).isZero();assertThat(count("llm_usage")).isZero();assertThat(count("workflow_instance")).isZero();
    }
    private void rejectedWithoutSourceMutation() {
        var snapshot=sourceSnapshot();assertThatThrownBy(()->fixture.migrate()).isInstanceOf(Exception.class);
        assertNoImport();assertThat(sourceSnapshot()).isEqualTo(snapshot);
    }

    @Test void allThirtyThreeSourceColumnsSurviveWithoutInventingAnOwnerOrChangingUtcOrRequestHash() throws Exception {
        seed();var snapshot=sourceSnapshot();fixture.migrate();
        assertThat(sourceSnapshot()).isEqualTo(snapshot);
        assertThat(count("workflow_instance")).isZero();assertThat(count("audit_event")).isEqualTo(10);assertThat(count("llm_usage")).isEqualTo(8);
        assertThat(target.queryForList("SELECT model_id,total_tokens,warning_percent,free_only,expires_at,version,updated_by,updated_at FROM llm_quota WHERE scope_type='MODEL' ORDER BY model_id"))
                .isEqualTo(source.queryForList("SELECT model_id,total_tokens,warning_percent,free_only,expires_at,CAST(version AS SIGNED) version,updated_by,updated_at FROM agent_model_budget ORDER BY model_id"));
        var expectedAttempts=source.query("SELECT *,DATE_FORMAT(started_at,'%Y-%m-%d %H:%i:%s.%f') start_text,DATE_FORMAT(finished_at,'%Y-%m-%d %H:%i:%s.%f') finish_text FROM agent_model_budget_attempt ORDER BY id",
                (rs,row)->new LegacyModelBudgetRecords.AttemptV1(rs.getString("id"),rs.getString("attempt_id"),rs.getString("model_id"),rs.getString("status"),
                        rs.getObject("input_tokens",Long.class),rs.getObject("output_tokens",Long.class),rs.getObject("cached_tokens",Long.class),rs.getString("start_text"),rs.getString("finish_text")));
        for(var expected:expectedAttempts) {
            var event=target.queryForMap("SELECT * FROM audit_event WHERE kind='LLM_LEGACY_ATTEMPT' AND legacy_key=?",expected.legacyId());
            assertThat(json.readValue((String)event.get("payload_json"),LegacyModelBudgetRecords.AttemptV1.class)).isEqualTo(expected);
            assertThat(event).containsEntry("owner_user_id",null).containsEntry("actor_user_id",null).containsEntry("request_id",expected.attemptId());
            assertThat(target.queryForMap("SELECT root_operation_id,operation_id,actor_user_id,input_tokens,output_tokens,cached_tokens,spent_delta FROM llm_usage WHERE source_audit_event_id=?",event.get("id")))
                    .containsEntry("root_operation_id",null).containsEntry("operation_id",null).containsEntry("actor_user_id",null)
                    .containsEntry("input_tokens",expected.inputTokens()).containsEntry("output_tokens",expected.outputTokens()).containsEntry("cached_tokens",expected.cachedTokens())
                    .containsEntry("spent_delta",(expected.inputTokens()==null?0:expected.inputTokens())+(expected.outputTokens()==null?0:expected.outputTokens()));
        }
        var expectedAudit=source.queryForObject("SELECT *,CAST(detail_json AS CHAR) detail_text,DATE_FORMAT(created_at,'%Y-%m-%d %H:%i:%s.%f') created_text FROM agent_model_budget_audit WHERE id=31",
                (rs,row)->new LegacyModelBudgetRecords.AuditV1(rs.getString("id"),rs.getString("model_id"),rs.getLong("actor_user_id"),rs.getString("action_name"),rs.getInt("version"),rs.getString("detail_text"),rs.getString("created_text")));
        assertThat(json.readValue(target.queryForObject("SELECT payload_json FROM audit_event WHERE kind='LLM_LEGACY_BUDGET_AUDIT'",String.class),LegacyModelBudgetRecords.AuditV1.class)).isEqualTo(expectedAudit);
        assertThat(target.queryForMap("SELECT CAST(legacy_key AS SIGNED) id,resource_id model_id,quantity remaining_tokens,observed_at,JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.sourceNote')) source_note,actor_user_id,request_id,content_sha256 request_sha256,occurred_at created_at FROM audit_event WHERE kind='MODEL_QUOTA_OBSERVATION'"))
                .isEqualTo(source.queryForMap("SELECT * FROM agent_model_budget_observation WHERE id=21"));
        assertThat(target.queryForObject("SELECT observed_at FROM audit_event WHERE kind='MODEL_QUOTA_OBSERVATION'",LocalDateTime.class)).isEqualTo(START);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM users WHERE id=999",Long.class)).isZero();
        assertThat(account(A)).containsEntry("spent_tokens",38L).containsEntry("unreconciled_legacy_attempts",4L).containsEntry("reserved_tokens",0L);
        assertThat(account(B)).containsEntry("spent_tokens",0L).containsEntry("unreconciled_legacy_attempts",1L);
        assertThat(account(C)).containsEntry("spent_tokens",7L).containsEntry("unreconciled_legacy_attempts",1L);
        assertThat(account(D)).containsEntry("spent_tokens",0L).containsEntry("unreconciled_legacy_attempts",0L);
        assertThat(target.queryForMap("SELECT spent_tokens,reserved_tokens,total_tokens FROM llm_quota WHERE scope_type='USER'"))
                .containsEntry("spent_tokens",0L).containsEntry("reserved_tokens",0L).containsEntry("total_tokens",777L);
        assertThatThrownBy(()->fixture.migrate()).isInstanceOf(Exception.class);
        assertThat(count("llm_usage")).isEqualTo(8);assertThat(account(A)).containsEntry("spent_tokens",38L);
    }

    @Test void importedFailureAndCancellationStayUncertainWhileUnlimitedPermissionAndLegacyOverviewRemainVisible() throws Exception {
        seed();fixture.migrate();
        var directory=mock(BusinessUserDirectory.class);
        when(directory.authenticated()).thenReturn(new BusinessUserDirectory.Identity(3,"migration-owner",true));
        when(directory.current(3,"migration-owner")).thenReturn(new BusinessUserDirectory.Identity(3,"migration-owner",true));
        var overview=new ModelBudgetService(target,directory,json).overview();
        var row=overview.stream().filter(v->A.equals(v.get("model_id"))).findFirst().orElseThrow();
        assertThat(row).containsEntry("available_tokens",null).containsEntry("remaining_upper_bound",962L).containsEntry("alert","USAGE_INCOMPLETE");
        @SuppressWarnings("unchecked") var usage=(Map<String,Object>)row.get("usage");
        assertThat(((Number)usage.get("attempts")).longValue()).isEqualTo(6);
        assertThat(((Number)usage.get("legacyAttempts")).longValue()).isEqualTo(6);
        assertThat(((Number)usage.get("unknownAttempts")).longValue()).isEqualTo(4);
        assertThat(((Number)usage.get("activeAttempts")).longValue()).isEqualTo(1);
        var store=new QuotaAccountStore(target);var limited=newAttempt(A);var failed=newAttempt(C);var unlimited=newAttempt(B);
        for(var rejected:List.of(limited,failed))assertThatThrownBy(()->tx.execute(status->store.reserve(rejected.root(),rejected.id(),3,rejected.model(),10)))
                .isInstanceOf(ModelBudgetService.Exhausted.class).hasMessageContaining("历史用量");
        assertThat(tx.execute(status->store.reserve(unlimited.root(),unlimited.id(),3,B,10)).created()).isTrue();
        assertThat(account(B)).containsEntry("reserved_tokens",10L).containsEntry("unreconciled_legacy_attempts",1L);
        assertThat(account(A)).containsEntry("reserved_tokens",0L);
        assertThat(target.queryForObject("SELECT spent_tokens+reserved_tokens FROM llm_quota WHERE scope_type='USER'",Long.class)).isZero();
    }

    @Test void missingWarningRuleCannotBeHiddenByAnotherAllowedTotalRule() {
        seed();String constraint=source.queryForObject("SELECT t.constraint_name FROM information_schema.table_constraints t JOIN information_schema.check_constraints c ON t.constraint_schema=c.constraint_schema AND t.constraint_name=c.constraint_name WHERE t.table_schema=DATABASE() AND t.table_name='agent_model_budget' AND c.check_clause LIKE '%warning_percent%'",String.class);
        assertThat(constraint).matches("[A-Za-z0-9_]+");
        source.execute("ALTER TABLE agent_model_budget DROP CHECK `"+constraint+"`");
        source.execute("ALTER TABLE agent_model_budget ADD CONSTRAINT duplicate_total CHECK(total_tokens IS NULL OR total_tokens>=0)");
        rejectedWithoutSourceMutation();
    }

    @ParameterizedTest @ValueSource(strings={"column","collation","type","trigger"})
    void changedSourceContractIsRejectedBeforeAnyImport(String mutation) {
        seed();switch(mutation) {
            case "column" -> source.execute("ALTER TABLE agent_model_budget_attempt ADD unknown_evidence VARCHAR(20) NULL");
            case "collation" -> source.execute("ALTER TABLE agent_model_budget MODIFY model_id VARCHAR(180) COLLATE utf8mb4_bin NOT NULL");
            case "type" -> source.execute("ALTER TABLE agent_model_budget_attempt MODIFY cached_tokens DECIMAL(20,0) NULL");
            case "trigger" -> source.execute("CREATE TRIGGER changed_v64_source BEFORE INSERT ON agent_model_budget FOR EACH ROW SET NEW.version=NEW.version");
            default -> throw new AssertionError(mutation);
        }
        rejectedWithoutSourceMutation();
    }

    @Test void orphanModelIsNotDroppedOrAssignedToAnotherPolicy() {
        seed();attempt(99,"orphan","dashscope:absent","COMPLETED",1L,2L,null,FINISH);rejectedWithoutSourceMutation();
    }
    @ParameterizedTest @ValueSource(strings={"component","aggregate"})
    void signedBigintOverflowIsRejectedBeforeCountersAreWritten(String mode) {
        seed();attempt(99,"overflow",D,"COMPLETED",Long.MAX_VALUE,"component".equals(mode)?1L:0L,null,FINISH);
        if("aggregate".equals(mode))attempt(100,"overflow-two",D,"COMPLETED",1L,0L,null,FINISH);
        rejectedWithoutSourceMutation();
    }

    @ParameterizedTest @ValueSource(strings={"missing_payload","original_hash","legacy_space","scope_space","period_space","entry_type_space","entry_key_space"})
    void targetCorruptionRollsBackTheEntireImport(String mutation) throws Exception {
        seed();String ddl=switch(mutation) {
            case "missing_payload" -> "CREATE TRIGGER damage_import BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.payload_json=IF(NEW.kind='LLM_LEGACY_ATTEMPT',JSON_REMOVE(NEW.payload_json,'$.finishedAtUtc'),NEW.payload_json)";
            case "original_hash" -> "CREATE TRIGGER damage_import BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.content_sha256=IF(NEW.kind='MODEL_QUOTA_OBSERVATION',REPEAT('0',64),NEW.content_sha256)";
            case "legacy_space" -> "CREATE TRIGGER damage_import BEFORE INSERT ON audit_event FOR EACH ROW SET NEW.legacy_source=CONCAT(NEW.legacy_source,' ')";
            case "scope_space" -> "CREATE TRIGGER damage_import BEFORE INSERT ON llm_quota FOR EACH ROW SET NEW.scope_type=CONCAT(NEW.scope_type,' ')";
            case "period_space" -> "CREATE TRIGGER damage_import BEFORE INSERT ON llm_quota FOR EACH ROW SET NEW.period_key=CONCAT(NEW.period_key,' ')";
            case "entry_type_space" -> "CREATE TRIGGER damage_import BEFORE INSERT ON llm_usage FOR EACH ROW SET NEW.entry_type=CONCAT(NEW.entry_type,' ')";
            case "entry_key_space" -> "CREATE TRIGGER damage_import BEFORE INSERT ON llm_usage FOR EACH ROW SET NEW.entry_key=CONCAT(NEW.entry_key,' ')";
            default -> throw new AssertionError(mutation);
        };
        fixture.targetSql(ddl+";",";");rejectedWithoutSourceMutation();
    }

    @Test void importedProvenanceAndUncertaintyCannotBeDetachedOrRecharged() throws Exception {
        seed();fixture.migrate();
        long id=target.queryForObject("SELECT MIN(id) FROM llm_usage",Long.class);
        assertThatThrownBy(()->target.update("DELETE FROM audit_event WHERE id=(SELECT source_audit_event_id FROM llm_usage WHERE id=?)",id)).isInstanceOf(DataAccessException.class);
        assertThatThrownBy(()->target.update("UPDATE llm_usage SET source_audit_event_id=NULL WHERE id=?",id)).isInstanceOf(DataAccessException.class);
        assertThatThrownBy(()->target.update("UPDATE llm_usage SET entry_type='SETTLE' WHERE id=?",id)).isInstanceOf(DataAccessException.class);
        assertThatThrownBy(()->target.update("UPDATE llm_usage SET actor_user_id=3 WHERE id=?",id)).isInstanceOf(DataAccessException.class);
        assertThatThrownBy(()->target.update("INSERT INTO llm_usage(account_id,source_audit_event_id,entry_key,entry_type,reserved_delta,spent_delta,input_tokens,output_tokens,cached_tokens,request_sha256,created_at) SELECT account_id,source_audit_event_id,entry_key,entry_type,reserved_delta,spent_delta,input_tokens,output_tokens,cached_tokens,request_sha256,created_at FROM llm_usage WHERE id=?",id)).isInstanceOf(DataAccessException.class);
        assertThatThrownBy(()->target.update("UPDATE llm_quota SET unreconciled_legacy_attempts=0 WHERE scope_type='MODEL' AND model_id=?",A)).isInstanceOf(DataAccessException.class);
        assertThatThrownBy(()->target.update("DELETE FROM llm_quota WHERE scope_type='MODEL' AND model_id=?",A)).isInstanceOf(DataAccessException.class);
        assertThat(count("llm_usage")).isEqualTo(8);
    }

    @Test void realEmptySourceStillRunsAllContractChecks() throws Exception {fixture.migrate();assertNoImport();}

    private record Attempt(long root,long id,String model) { }
    private Attempt newAttempt(String model) {
        String root=UUID.randomUUID().toString(),id=UUID.randomUUID().toString();
        target.update("INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,actor_user_id,status,payload_version,payload_json) VALUES(?,'LLM_REQUEST','OWNER:3',?,?,3,3,'OPEN',1,'{}')",root,root,"a".repeat(64));
        long parent=target.queryForObject("SELECT id FROM workflow_instance WHERE workflow_id=?",Long.class,root);
        target.update("INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,actor_user_id,parent_workflow_id,resource_type,resource_id,status,payload_version,payload_json) VALUES(?,'LLM_PROVIDER_ATTEMPT',?,?,?,3,3,?,'LLM_MODEL',?,'RESERVED',1,'{}')",id,"LLM_REQUEST:"+parent,id,"a".repeat(64),parent,model);
        return new Attempt(parent,target.queryForObject("SELECT id FROM workflow_instance WHERE workflow_id=?",Long.class,id),model);
    }
}
