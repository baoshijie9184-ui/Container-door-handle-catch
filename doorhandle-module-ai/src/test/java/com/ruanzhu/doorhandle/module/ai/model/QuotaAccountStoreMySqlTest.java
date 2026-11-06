package com.ruanzhu.doorhandle.module.ai.model;

import com.ruanzhu.doorhandle.module.ai.testsupport.CompactQuotaFixture;
import com.ruanzhu.doorhandle.module.ai.testsupport.FeatureMySql;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import static org.assertj.core.api.Assertions.*;

/** Native locking, constraints and rollback; never falls back to an in-memory database. */
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
@EnabledIfSystemProperty(named="doorhandle.feature.mysql.config",matches=".+")
class QuotaAccountStoreMySqlTest {
    static final String MODEL="dashscope:qwen-quota-fixture";
    CompactQuotaFixture fixture;JdbcTemplate jdbc;TransactionTemplate tx;QuotaAccountStore store;
    record Attempt(long root,long id) { }

    @BeforeEach void start() throws Exception {
        var source=FeatureMySql.source();fixture=new CompactQuotaFixture(source);jdbc=new JdbcTemplate(source);
        store=new QuotaAccountStore(jdbc);tx=new TransactionTemplate(new DataSourceTransactionManager(source));
        tx.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
        jdbc.update("INSERT INTO users(id,username,password) VALUES(3,'quota-owner','fixture'),(4,'quota-other','fixture')");
    }
    @AfterEach void close(){if(fixture!=null)fixture.close();}
    long account(String scope,Long owner,long limit) {
        jdbc.update("""
                INSERT INTO llm_quota(scope_type,owner_user_id,model_id,period_key,total_tokens,created_at,updated_at)
                VALUES(?,?,?,'TOTAL',?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))
                """,scope,owner,MODEL,limit);
        return jdbc.queryForObject("SELECT id FROM llm_quota WHERE scope_type=? AND subject_key=? AND model_id=?",Long.class,scope,owner==null?0:owner,MODEL);
    }
    Attempt attempt(long owner) {
        String rootId=UUID.randomUUID().toString(),attemptId=UUID.randomUUID().toString(),hash="a".repeat(64);
        jdbc.update("""
                INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,actor_user_id,status,payload_version,payload_json)
                VALUES(?,'LLM_REQUEST',?,?,?, ?,?,'OPEN',1,'{}')
                """,rootId,"OWNER:"+owner,rootId,hash,owner,owner);
        long root=jdbc.queryForObject("SELECT id FROM workflow_instance WHERE workflow_id=?",Long.class,rootId);
        jdbc.update("""
                INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,actor_user_id,
                  parent_workflow_id,resource_type,resource_id,status,payload_version,payload_json)
                VALUES(?,'LLM_PROVIDER_ATTEMPT',?,?,?, ?,?,?,'LLM_MODEL',?,'RESERVED',1,'{}')
                """,attemptId,"LLM_REQUEST:"+root,attemptId,hash,owner,owner,root,MODEL);
        return new Attempt(root,jdbc.queryForObject("SELECT id FROM workflow_instance WHERE workflow_id=?",Long.class,attemptId));
    }
    QuotaAccountStore.Reservation reserve(Attempt a,long owner,long ceiling) {
        return tx.execute(status->store.reserve(a.root(),a.id(),owner,MODEL,ceiling));
    }
    QuotaAccountStore.Settlement settle(Attempt a,long input,long output,Long cached) {
        return tx.execute(status->store.settle(a.root(),a.id(),3,MODEL,input,output,cached));
    }
    Map<String,Object> balance(long id){return jdbc.queryForMap("SELECT reserved_tokens,spent_tokens FROM llm_quota WHERE id=?",id);}
    void dispatched(Attempt a){jdbc.update("UPDATE workflow_instance SET status='STARTED' WHERE id=?",a.id());}

    @Test void enterpriseAndPersonalBalancesSettleAtomicallyAndCachedTokensAreNotDoubleCharged() {
        long enterprise=account("MODEL",null,100),personal=account("USER",3L,70);var a=attempt(3);
        assertThat(reserve(a,3,50).created()).isTrue();assertThat(reserve(a,3,50).created()).isFalse();
        dispatched(a);assertThat(settle(a,20,10,5L).created()).isTrue();
        assertThat(settle(a,20,10,5L).created()).isFalse();
        for(long id:new long[]{enterprise,personal})assertThat(balance(id)).containsEntry("reserved_tokens",0L).containsEntry("spent_tokens",30L);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_usage",Long.class)).isEqualTo(4);
        assertThatThrownBy(()->settle(a,20,11,5L)).hasMessageContaining("内容不一致");
    }
    @Test void absentPersonalQuotaPreservesPermissionAndLaterGrantDoesNotChargeAnEarlierAdmission() {
        long enterprise=account("MODEL",null,100);var a=attempt(3);
        assertThat(reserve(a,3,50).accounts()).hasSize(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_quota WHERE scope_type='USER'",Long.class)).isZero();
        long personal=account("USER",3L,40);
        assertThat(reserve(a,3,50).accounts()).hasSize(1);
        dispatched(a);settle(a,10,5,null);
        assertThat(balance(enterprise)).containsEntry("spent_tokens",15L);
        assertThat(balance(personal)).containsEntry("reserved_tokens",0L).containsEntry("spent_tokens",0L);
    }
    @Test void insufficientPersonalQuotaDoesNotLeaveAnEnterpriseReservation() {
        long enterprise=account("MODEL",null,100);account("USER",3L,10);var a=attempt(3);
        assertThatThrownBy(()->reserve(a,3,50)).isInstanceOf(ModelBudgetService.Exhausted.class);
        assertThat(balance(enterprise)).containsEntry("reserved_tokens",0L);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_usage",Long.class)).isZero();
    }
    @Test void concurrentAdmissionsCannotReserveTheSameAvailableTokens() throws Exception {
        long enterprise=account("MODEL",null,100);account("USER",3L,100);
        var a=attempt(3);var b=attempt(3);var gate=new CountDownLatch(1);var executor=Executors.newFixedThreadPool(2);
        try {
            var first=executor.submit(()->{gate.await();try{reserve(a,3,60);return true;}catch(ModelBudgetService.Exhausted exhausted){return false;}});
            var second=executor.submit(()->{gate.await();try{reserve(b,3,60);return true;}catch(ModelBudgetService.Exhausted exhausted){return false;}});
            gate.countDown();assertThat(first.get(10,TimeUnit.SECONDS)^second.get(10,TimeUnit.SECONDS)).isTrue();
            assertThat(balance(enterprise)).containsEntry("reserved_tokens",60L).containsEntry("spent_tokens",0L);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_usage",Long.class)).isEqualTo(2);
        } finally {executor.shutdownNow();}
    }
    @Test void uncertainDispatchCannotReleaseTokensAndCanLaterSettleTheActualReport() {
        long enterprise=account("MODEL",null,100);var a=attempt(3);reserve(a,3,60);dispatched(a);
        assertThatThrownBy(()->tx.execute(status->store.cancelBeforeDispatch(a.root(),a.id(),3,MODEL))).hasMessageContaining("possibly dispatched");
        jdbc.update("UPDATE workflow_instance SET status='NEEDS_REVIEW' WHERE id=?",a.id());
        assertThatThrownBy(()->tx.execute(status->store.cancelBeforeDispatch(a.root(),a.id(),3,MODEL))).hasMessageContaining("possibly dispatched");
        assertThat(balance(enterprise)).containsEntry("reserved_tokens",60L);
        settle(a,8,2,null);assertThat(balance(enterprise)).containsEntry("reserved_tokens",0L).containsEntry("spent_tokens",10L);
    }
    @Test void cancellationBeforeDispatchIsIdempotentAndCannotAlsoSettle() {
        long enterprise=account("MODEL",null,100);var a=attempt(3);reserve(a,3,50);
        assertThat((Boolean)tx.execute(status->store.cancelBeforeDispatch(a.root(),a.id(),3,MODEL))).isTrue();
        assertThat((Boolean)tx.execute(status->store.cancelBeforeDispatch(a.root(),a.id(),3,MODEL))).isFalse();
        assertThatThrownBy(()->settle(a,0,0,null)).hasMessageContaining("内容不一致");
        assertThat(balance(enterprise)).containsEntry("reserved_tokens",0L).containsEntry("spent_tokens",0L);
    }
    @Test void secondAccountLedgerFailureRollsBackBothBalancesAndAllEntries() {
        long enterprise=account("MODEL",null,100),personal=account("USER",3L,100);var a=attempt(3);
        jdbc.execute("ALTER TABLE llm_usage ADD CONSTRAINT reject_personal_entry CHECK(account_id<>"+personal+")");
        try {
            assertThatThrownBy(()->reserve(a,3,50)).isInstanceOf(org.springframework.dao.DataAccessException.class);
            for(long id:new long[]{enterprise,personal})assertThat(balance(id)).containsEntry("reserved_tokens",0L).containsEntry("spent_tokens",0L);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_usage",Long.class)).isZero();
        } finally {jdbc.execute("ALTER TABLE llm_usage DROP CHECK reject_personal_entry");}
    }
    @Test void unexpectedProviderOverrunIsRecordedInFullAndBlocksFurtherAdmission() {
        long enterprise=account("MODEL",null,100);var a=attempt(3);reserve(a,3,50);dispatched(a);
        assertThat(settle(a,100,21,null).exceedsCurrentLimit()).isTrue();
        assertThat(balance(enterprise)).containsEntry("reserved_tokens",0L).containsEntry("spent_tokens",121L);
        var b=attempt(3);assertThatThrownBy(()->reserve(b,3,1)).isInstanceOf(ModelBudgetService.Exhausted.class);
    }
    @Test void mismatchedOwnerAndRootCannotWriteAnotherUsersQuota() {
        account("MODEL",null,100);var a=attempt(3);var b=attempt(4);
        assertThatThrownBy(()->reserve(a,4,20)).hasMessageContaining("ownership");
        assertThatThrownBy(()->tx.execute(status->store.reserve(a.root(),b.id(),3,MODEL,20))).hasMessageContaining("ownership");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_usage",Long.class)).isZero();
    }
    @Test void incompleteHistoricalUsageBlocksLimitedAdmissionBeforeEitherAccountIsCharged() {
        long enterprise=account("MODEL",null,1000),personal=account("USER",3L,1000);var a=attempt(3);
        jdbc.update("UPDATE llm_quota SET unreconciled_legacy_attempts=2 WHERE id=?",enterprise);
        assertThatThrownBy(()->reserve(a,3,10)).isInstanceOf(ModelBudgetService.Exhausted.class).hasMessageContaining("历史用量");
        assertThat(balance(enterprise)).containsEntry("reserved_tokens",0L);assertThat(balance(personal)).containsEntry("reserved_tokens",0L);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_usage",Long.class)).isZero();
    }
    @Test void unlimitedHistoricalAccountRetainsAccessWithoutClearingUnresolvedEvidence() {
        long enterprise=account("MODEL",null,1000);var a=attempt(3);
        jdbc.update("UPDATE llm_quota SET total_tokens=NULL,unreconciled_legacy_attempts=2 WHERE id=?",enterprise);
        var admission=reserve(a,3,10);assertThat(admission.created()).isTrue();assertThat(admission.accounts().get(0).unreconciledLegacyAttempts()).isEqualTo(2L);
        dispatched(a);settle(a,5,3,null);
        assertThat(balance(enterprise)).containsEntry("spent_tokens",8L).containsEntry("reserved_tokens",0L);
        assertThat(jdbc.queryForObject("SELECT unreconciled_legacy_attempts FROM llm_quota WHERE id=?",Long.class,enterprise)).isEqualTo(2L);
    }
    @Test void historicalUncertaintyCannotBeDeletedResetOrMovedToAnotherAccount() {
        long enterprise=account("MODEL",null,1000);jdbc.update("UPDATE llm_quota SET unreconciled_legacy_attempts=1 WHERE id=?",enterprise);
        assertThatThrownBy(()->jdbc.update("DELETE FROM llm_quota WHERE id=?",enterprise)).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThatThrownBy(()->jdbc.update("UPDATE llm_quota SET unreconciled_legacy_attempts=0 WHERE id=?",enterprise)).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThatThrownBy(()->jdbc.update("UPDATE llm_quota SET model_id='dashscope:other-fixture' WHERE id=?",enterprise)).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(jdbc.update("UPDATE llm_quota SET total_tokens=2000,version=version+1 WHERE id=?",enterprise)).isEqualTo(1);
    }
}
