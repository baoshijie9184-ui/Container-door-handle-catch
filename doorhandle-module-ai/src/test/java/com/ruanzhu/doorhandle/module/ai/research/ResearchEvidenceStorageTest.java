package com.ruanzhu.doorhandle.module.ai.research;

import io.agentscope.core.message.ToolResultBlock;
import org.junit.jupiter.api.*;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.*;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;

/** 同时继承全部来源登记回归，在开启治理时重新验证原有语义。 */
class ResearchEvidenceStorageTest extends ResearchEvidenceServiceTest {
    ResearchEvidenceProperties storageProperties;
    ResearchEvidenceStorage storage;
    @Override @BeforeEach protected void setup() throws Exception {
        super.setup();migrate(Path.of("src/main/resources/db/migration-V32-agent-research-storage.sql"));
        storageProperties=new ResearchEvidenceProperties();storageProperties.setEnabled(true);storageProperties.setGovernanceEnabled(true);
        storage=new ResearchEvidenceStorage(jdbc,transactions,storageProperties);storage.schema();
        evidence=new ResearchEvidenceService(jdbc,transactions,json,journal,storage);evidence.schema();
    }
    @AfterEach void stopMaintenance(){if(storage!=null)storage.close();}
    void expire(String sourceId){jdbc.update("UPDATE agent_research_source SET expires_at=? WHERE source_id=?",LocalDateTime.now().minusDays(1),sourceId);}
    @Test void accountQuotaSpansRunsIsolatedByStableUserAndExpiresWithoutDeletingHistory(){
        storageProperties.setMaxSourcesPerUser(2);
        var first=begin(alice,"first");String id=capture(first,"call-1","fact");
        var second=begin(alice,"second");capture(second,"call-2","fact");
        var third=begin(alice,"third");
        assertThatThrownBy(()->capture(third,"call-3","fact")).isInstanceOf(ResearchEvidenceStorage.QuotaExceeded.class);
        var own=begin(bob,"boss");evidence.capture(bob,own.id(),"boss-call",args(),ToolResultBlock.text("boss fact"));
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_research_source WHERE user_id=1",Integer.class)).isEqualTo(2);
        expire(id);capture(third,"call-3","fact");
        assertThat(evidence.view(alice,first.id()).expiredSourceCount()).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_research_source WHERE user_id=1",Integer.class)).isEqualTo(3);
    }
    @Test void identicalCallAtCapacityRemainsIdempotentAndUnauthorizedRunDoesNotReserveQuota(){
        storageProperties.setMaxSourcesPerUser(1);var run=begin(alice,"one");String id=capture(run,"same","fact");
        assertThat(capture(run,"same","fact")).isEqualTo(id);
        assertThatThrownBy(()->evidence.capture(bob,run.id(),"forged",args(),ToolResultBlock.text("private"))).hasMessageContaining("404");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_research_storage_owner WHERE user_id=2",Integer.class)).isZero();
    }
    @Test void concurrentRunsCannotExceedOneAccountQuota() throws Exception {
        storageProperties.setMaxSourcesPerUser(1);var a=begin(alice,"one");var b=begin(alice,"two");
        var workers=Executors.newFixedThreadPool(2);var ready=new CountDownLatch(1);
        try{
            var calls=new ArrayList<Future<Boolean>>();for(var run:List.of(a,b))calls.add(workers.submit(()->{ready.await();try{evidence.capture(alice,run.id(),"call",args(),ToolResultBlock.text("fact"));return true;}catch(ResearchEvidenceStorage.QuotaExceeded error){return false;}}));
            ready.countDown();int successful=0;for(var call:calls)if(call.get(5,TimeUnit.SECONDS))successful++;
            assertThat(successful).isEqualTo(1);assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_research_source",Integer.class)).isEqualTo(1);
        }finally{workers.shutdownNow();}
    }
    @Test void expiredPayloadErasureKeepsCitationIdentityHashesAndExpiredCounts(){
        var run=begin(alice,"one");String id=capture(run,"call","PRIVATE_EXPIRED_SNIPPET");
        String answer="fact [source:"+id+"]";evidence.recordAnswer(alice,run.id(),answer);run.finish("COMPLETED");
        var before=jdbc.queryForMap("SELECT * FROM agent_research_source WHERE source_id=?",id);expire(id);
        storageProperties.setPurgeEnabled(true);assertThat(storage.purgeExpiredBatch()).isEqualTo(1);assertThat(storage.purgeExpiredBatch()).isZero();
        var after=jdbc.queryForMap("SELECT * FROM agent_research_source WHERE source_id=?",id);
        for(String field:List.of("requested_url","title","excerpt"))assertThat(after.get(field)).isEqualTo("");
        for(String field:List.of("source_id","run_id","call_id","content_sha256","request_sha256"))assertThat(after.get(field)).isEqualTo(before.get(field));
        var view=evidence.view(alice,run.id());assertThat(view.sources()).isEmpty();assertThat(view.expiredSourceCount()).isEqualTo(1);
        assertThat(view.answerSha256()).isEqualTo(ResearchEvidenceService.sha256(answer));assertThat(view.citations()).hasSize(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_research_content_purge",Integer.class)).isEqualTo(1);
        assertThat(jdbc.queryForMap("SELECT * FROM agent_research_content_purge").toString()).doesNotContain("PRIVATE_","1.1.1.1");
    }
    @Test void cleanupIsOffByDefaultNeverErasesActiveSourcesAndHonorsBatchLimit(){
        var run=begin(alice,"one");String old=capture(run,"old","old fact"),active=capture(run,"active","PRIVATE_ACTIVE_SNIPPET");expire(old);
        assertThat(storage.purgeExpiredBatch()).isZero();assertThat(jdbc.queryForObject("SELECT excerpt FROM agent_research_source WHERE source_id=?",String.class,old)).isNotEmpty();
        String other=capture(run,"other","another fact");expire(other);storageProperties.setCleanupBatchSize(1);storageProperties.setPurgeEnabled(true);
        assertThat(storage.purgeExpiredBatch()).isEqualTo(1);assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_research_content_purge",Integer.class)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT excerpt FROM agent_research_source WHERE source_id=?",String.class,active)).isEqualTo("PRIVATE_ACTIVE_SNIPPET");
    }
    @Test void auditFailureRollsBackContentErasure(){
        var run=begin(alice,"one");String id=capture(run,"call","PRIVATE_EXPIRED_SNIPPET");expire(id);
        jdbc.execute("ALTER TABLE agent_research_content_purge ADD CONSTRAINT reject_purge_audit CHECK(cleared_chars<0)");
        storageProperties.setPurgeEnabled(true);assertThatThrownBy(()->storage.purgeExpiredBatch()).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(jdbc.queryForObject("SELECT excerpt FROM agent_research_source WHERE source_id=?",String.class,id)).isEqualTo("PRIVATE_EXPIRED_SNIPPET");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_research_content_purge",Integer.class)).isZero();
    }
    @Test void twoMaintenanceInstancesDoNotDoublePurgeOrDoubleAudit() throws Exception {
        var run=begin(alice,"one");String id=capture(run,"call","old fact");expire(id);
        var workers=Executors.newFixedThreadPool(2);
        try(var other=new ResearchEvidenceStorage(jdbc,transactions,storageProperties)){
            other.schema();storageProperties.setPurgeEnabled(true);
            var first=workers.submit(storage::purgeExpiredBatch);var second=workers.submit(other::purgeExpiredBatch);
            assertThat(first.get(5,TimeUnit.SECONDS)+second.get(5,TimeUnit.SECONDS)).isEqualTo(1);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_research_content_purge",Integer.class)).isEqualTo(1);
        }finally{workers.shutdownNow();}
    }
    @Test void invalidConfigurationAndOutOfTransactionQuotaChecksAreRejected(){
        assertThatThrownBy(()->storage.lockOwner(alice)).isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(()->storage.checkCapacity(alice)).isInstanceOf(IllegalStateException.class);
        storageProperties.setMaxSourcesPerUser(0);assertThatThrownBy(storage::schema).isInstanceOf(IllegalStateException.class);
        storageProperties.setMaxSourcesPerUser(500);storageProperties.setCleanupBatchSize(501);assertThatThrownBy(storage::schema).isInstanceOf(IllegalStateException.class);
    }
}
