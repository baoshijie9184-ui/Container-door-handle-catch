package com.ruanzhu.doorhandle.module.ai.research;

import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.transaction.support.TransactionTemplate;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;

class ResearchExportRateLimitTest {
    @TempDir Path workspace;
    final ResearchEvidenceServiceTest fixture=new ResearchEvidenceServiceTest();
    ResearchEvidenceProperties properties;
    ResearchExportRateLimit limiter;
    ResearchEvidenceExportService exports;
    @BeforeEach void setup() throws Exception {
        fixture.workspace=workspace;fixture.setup();
        fixture.migrate(Path.of("src/main/resources/db/migration-V33-agent-research-export.sql"));
        fixture.migrate(Path.of("src/main/resources/db/migration-V35-agent-research-export-limit.sql"));
        properties=new ResearchEvidenceProperties();properties.setExportMaxPerWindow(1);
        limiter=new ResearchExportRateLimit(fixture.jdbc,properties);limiter.schema();exports=service();
    }
    ResearchEvidenceExportService service() {
        return new ResearchEvidenceExportService(fixture.evidence,fixture.jdbc,fixture.transactions,fixture.json,
                new ResearchExportRateLimit(fixture.jdbc,properties));
    }
    int count(){return fixture.jdbc.queryForObject("SELECT COALESCE(SUM(export_count),0) FROM agent_research_export_limit",Integer.class);}
    int audits(){return fixture.jdbc.queryForObject("SELECT COUNT(*) FROM agent_research_export_audit",Integer.class);}
    LocalDateTime now(){return fixture.jdbc.queryForObject("SELECT CURRENT_TIMESTAMP(6)",LocalDateTime.class);}
    @Test void allRunsAndServiceInstancesShareTheAccountsLimit() {
        var first=fixture.begin(fixture.alice,"first");var second=fixture.begin(fixture.alice,"second");
        exports.export(fixture.alice,first.id(),true);
        assertThatThrownBy(()->service().export(fixture.alice,second.id(),true)).isInstanceOfSatisfying(ResearchExportRateLimit.Limited.class,error->{
            assertThat(error.getStatusCode().value()).isEqualTo(429);
            assertThat(Long.parseLong(error.getHeaders().getFirst("Retry-After"))).isBetween(1L,60L);
        });
        assertThat(count()).isEqualTo(1);assertThat(audits()).isEqualTo(1);
    }
    @Test void otherAccountsHaveIndependentLimits() {
        var alice=fixture.begin(fixture.alice,"alice");var bob=fixture.begin(fixture.bob,"bob");
        exports.export(fixture.alice,alice.id(),true);exports.export(fixture.bob,bob.id(),true);
        assertThat(count()).isEqualTo(2);assertThat(audits()).isEqualTo(2);
    }
    @Test void concurrentServicesCannotBothTakeTheLastSlotIncludingTheFirstInsert() throws Exception {
        var first=fixture.begin(fixture.alice,"first");var second=fixture.begin(fixture.alice,"second");
        var other=service();var workers=Executors.newFixedThreadPool(2);var start=new CountDownLatch(1);
        try {
            var one=workers.submit(()->{start.await();return attempt(exports,first.id());});
            var two=workers.submit(()->{start.await();return attempt(other,second.id());});start.countDown();
            assertThat(one.get(10,TimeUnit.SECONDS)+two.get(10,TimeUnit.SECONDS)).isEqualTo(1);
            assertThat(count()).isEqualTo(1);assertThat(audits()).isEqualTo(1);
        } finally {workers.shutdownNow();}
    }
    private int attempt(ResearchEvidenceExportService service,String run) {
        try {service.export(fixture.alice,run,true);return 1;}
        catch(ResearchExportRateLimit.Limited expected){return 0;}
    }
    @Test void failedAuditRollsBackQuotaAndANewExplicitAttemptCanSucceed() {
        var run=fixture.begin(fixture.alice,"owned");
        fixture.jdbc.execute("ALTER TABLE agent_research_export_audit ADD CONSTRAINT reject_export CHECK(payload_bytes<0)");
        assertThatThrownBy(()->exports.export(fixture.alice,run.id(),true)).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(count()).isZero();assertThat(audits()).isZero();
        fixture.jdbc.execute("ALTER TABLE agent_research_export_audit DROP CONSTRAINT reject_export");
        exports.export(fixture.alice,run.id(),true);assertThat(count()).isEqualTo(1);assertThat(audits()).isEqualTo(1);
    }
    @Test void failedAuditAlsoRestoresAnExistingWindow() {
        properties.setExportMaxPerWindow(2);exports=service();var run=fixture.begin(fixture.alice,"owned");
        exports.export(fixture.alice,run.id(),true);
        fixture.jdbc.execute("ALTER TABLE agent_research_export_audit ADD CONSTRAINT reject_export CHECK(id=1)");
        assertThatThrownBy(()->exports.export(fixture.alice,run.id(),true)).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(count()).isEqualTo(1);assertThat(audits()).isEqualTo(1);
    }
    @Test void unconfirmedAndForeignRunsCannotCreateOrConsumeAWindowEvenWhenFull() {
        var run=fixture.begin(fixture.alice,"private");
        assertThatThrownBy(()->exports.export(fixture.alice,run.id(),false)).hasMessageContaining("400");
        assertThatThrownBy(()->exports.export(fixture.bob,run.id(),true)).hasMessageContaining("404");assertThat(count()).isZero();
        var bob=fixture.begin(fixture.bob,"bob");exports.export(fixture.bob,bob.id(),true);
        assertThatThrownBy(()->exports.export(fixture.bob,run.id(),true)).hasMessageContaining("404");assertThat(count()).isEqualTo(1);
    }
    @Test void expiredWindowResetsUsingDatabaseTimeAndDoesNotDeleteAuditHistory() {
        var run=fixture.begin(fixture.alice,"owned");exports.export(fixture.alice,run.id(),true);
        fixture.jdbc.update("UPDATE agent_research_export_limit SET window_ends_at=?",now().minusSeconds(1));
        exports.export(fixture.alice,run.id(),true);assertThat(count()).isEqualTo(1);assertThat(audits()).isEqualTo(2);
        var end=fixture.jdbc.queryForObject("SELECT window_ends_at FROM agent_research_export_limit",LocalDateTime.class);
        assertThat(end).isAfter(now().plusSeconds(55));
    }
    @Test void successfulExportsAtTheLimitRemainAllowedUntilTheNextAttempt() {
        properties.setExportMaxPerWindow(3);exports=service();var run=fixture.begin(fixture.alice,"owned");
        for(int i=0;i<3;i++)exports.export(fixture.alice,run.id(),true);
        assertThatThrownBy(()->exports.export(fixture.alice,run.id(),true)).isInstanceOf(ResearchExportRateLimit.Limited.class);
        assertThat(count()).isEqualTo(3);assertThat(audits()).isEqualTo(3);
    }
    @Test void limitFailurePreservesTheWindowAndRoundsRetryUp() {
        var run=fixture.begin(fixture.alice,"owned");exports.export(fixture.alice,run.id(),true);
        var end=now().plusSeconds(12).plusNanos(800000000);
        fixture.jdbc.update("UPDATE agent_research_export_limit SET window_ends_at=?",end);
        assertThatThrownBy(()->exports.export(fixture.alice,run.id(),true)).isInstanceOfSatisfying(ResearchExportRateLimit.Limited.class,error->
                assertThat(Long.parseLong(error.getHeaders().getFirst("Retry-After"))).isBetween(12L,13L));
        assertThat(fixture.jdbc.queryForObject("SELECT window_ends_at FROM agent_research_export_limit",LocalDateTime.class)).isEqualTo(end);
    }
    @Test void counterCannotBeUsedOutsideTheExportTransaction() {
        assertThatThrownBy(()->limiter.consume(fixture.alice)).isInstanceOf(IllegalStateException.class);assertThat(count()).isZero();
        var tx=new TransactionTemplate(fixture.transactions);
        tx.executeWithoutResult(status->{limiter.consume(fixture.alice);status.setRollbackOnly();});assertThat(count()).isZero();
    }
    @Test void missingMigrationFailsBeforeServingAnyExports() {
        fixture.jdbc.execute("DROP TABLE agent_research_export_limit");
        assertThatThrownBy(limiter::schema).hasMessageContaining("migration-V35-agent-research-export-limit.sql");
    }
    @Test void runtimeDatabaseFailureCannotSilentlyDisableTheLimit() {
        var run=fixture.begin(fixture.alice,"owned");fixture.jdbc.execute("DROP TABLE agent_research_export_limit");
        assertThatThrownBy(()->exports.export(fixture.alice,run.id(),true)).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(audits()).isZero();
    }
    @Test void contentIsReadAgainAfterQuotaAcquisitionInsteadOfUsingAnEarlierView() throws Exception {
        var run=fixture.begin(fixture.alice,"owned");String id=fixture.capture(run,"call","EXPIRED_DURING_QUOTA_WAIT");
        var reads=new java.util.concurrent.atomic.AtomicInteger();
        var evidence=org.mockito.Mockito.spy(fixture.evidence);
        org.mockito.Mockito.doAnswer(invocation->{
            var view=fixture.evidence.view(fixture.alice,run.id());
            if(reads.getAndIncrement()==0)fixture.jdbc.update("UPDATE agent_research_source SET expires_at=? WHERE source_id=?",now().minusSeconds(1),id);
            return view;
        }).when(evidence).view(fixture.alice,run.id());
        var service=new ResearchEvidenceExportService(evidence,fixture.jdbc,fixture.transactions,fixture.json,limiter);
        var document=fixture.json.readTree(service.export(fixture.alice,run.id(),true).bytes());
        assertThat(document.path("evidence").path("sources").size()).isZero();assertThat(reads.get()).isEqualTo(2);
        assertThat(document.toString()).doesNotContain("EXPIRED_DURING_QUOTA_WAIT");assertThat(audits()).isEqualTo(1);
    }
}
