package com.ruanzhu.doorhandle.module.ai.research;

import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;

class ResearchEvidenceExportServiceTest {
    @TempDir Path workspace;
    final ResearchEvidenceServiceTest fixture=new ResearchEvidenceServiceTest();
    ResearchEvidenceExportService exports;
    @BeforeEach void setup() throws Exception {
        fixture.workspace=workspace;fixture.setup();
        fixture.migrate(Path.of("src/main/resources/db/migration-V33-agent-research-export.sql"));
        exports=new ResearchEvidenceExportService(fixture.evidence,fixture.jdbc,fixture.transactions,fixture.json);exports.schema();
    }
    int audits(){return fixture.jdbc.queryForObject("SELECT COUNT(*) FROM agent_research_export_audit",Integer.class);}
    @Test void exportUsesCurrentOwnedViewWithExactByteHashAndMetadataOnlyReceipt() throws Exception {
        var run=fixture.begin(fixture.alice,"owned");String id=fixture.capture(run,"call","# 可核对标题\nPRIVATE_EXCERPT token=SECRET_VALUE");
        fixture.evidence.recordAnswer(fixture.alice,run.id(),"PRIVATE_ANSWER [source:"+id+"]");run.finish("COMPLETED");
        var file=exports.export(fixture.alice,run.id(),true);String text=new String(file.bytes(),StandardCharsets.UTF_8);
        var document=fixture.json.readTree(text);assertThat(document.path("version").asInt()).isEqualTo(1);
        assertThat(document.path("exportId").asText()).isEqualTo(file.exportId());
        assertThat(document.path("evidence").path("runId").asText()).isEqualTo(run.id());
        assertThat(document.path("evidence").path("sources").size()).isEqualTo(1);
        assertThat(document.path("evidence").path("citations").size()).isEqualTo(1);
        assertThat(text).contains("PRIVATE_EXCERPT","可核对标题").doesNotContain("SECRET_VALUE","private-query","PRIVATE_ANSWER","username");
        assertThat(file.sha256()).isEqualTo(ResearchEvidenceService.sha256(text));
        var audit=fixture.jdbc.queryForMap("SELECT * FROM agent_research_export_audit");
        assertThat(audit.get("payload_sha256")).isEqualTo(file.sha256());assertThat(((Number)audit.get("payload_bytes")).intValue()).isEqualTo(file.bytes().length);
        assertThat(audit.toString()).doesNotContain("PRIVATE_EXCERPT","可核对标题","1.1.1.1","PRIVATE_ANSWER");
        assertThat(fixture.journal.get(fixture.alice,run.id()).status()).isEqualTo("COMPLETED");
    }
    @Test void exportRechecksExpiryAndRetainsOnlyHistoricalReferenceAndCount() throws Exception {
        var run=fixture.begin(fixture.alice,"owned");String id=fixture.capture(run,"call","EXPIRED_PRIVATE_BODY");
        fixture.evidence.recordAnswer(fixture.alice,run.id(),"fact [source:"+id+"]");
        fixture.jdbc.update("UPDATE agent_research_source SET expires_at=? WHERE source_id=?",LocalDateTime.now().minusDays(1),id);
        var file=exports.export(fixture.alice,run.id(),true);String text=new String(file.bytes(),StandardCharsets.UTF_8);var evidence=fixture.json.readTree(text).path("evidence");
        assertThat(evidence.path("sources").size()).isZero();assertThat(evidence.path("expiredSourceCount").asInt()).isEqualTo(1);
        assertThat(evidence.path("citations").get(0).path("sourceId").asText()).isEqualTo(id);
        assertThat(text).doesNotContain("EXPIRED_PRIVATE_BODY","1.1.1.1");
    }
    @Test void supervisorCannotExportAnotherAccountsPrivateResearch(){
        var run=fixture.begin(fixture.alice,"private");fixture.capture(run,"call","PRIVATE");
        assertThatThrownBy(()->exports.export(fixture.bob,run.id(),true)).hasMessageContaining("404");assertThat(audits()).isZero();
    }
    @Test void confirmationIsRequiredWithoutWritingAnAudit(){
        var run=fixture.begin(fixture.alice,"owned");
        assertThatThrownBy(()->exports.export(fixture.alice,run.id(),false)).hasMessageContaining("400");assertThat(audits()).isZero();
    }
    @Test void failedAuditDoesNotReturnAFileAndLeavesSourceUntouched(){
        var run=fixture.begin(fixture.alice,"owned");fixture.capture(run,"call","PRIVATE_EXCERPT");
        fixture.jdbc.execute("ALTER TABLE agent_research_export_audit ADD CONSTRAINT reject_export CHECK(payload_bytes<0)");
        assertThatThrownBy(()->exports.export(fixture.alice,run.id(),true)).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(audits()).isZero();assertThat(fixture.evidence.view(fixture.alice,run.id()).sources()).singleElement().satisfies(s->assertThat(s.excerpt()).isEqualTo("PRIVATE_EXCERPT"));
    }
    @Test void missingMigrationFailsBeforeServingExports(){
        fixture.jdbc.execute("DROP TABLE agent_research_export_audit");
        assertThatThrownBy(exports::schema).hasMessageContaining("migration-V33-agent-research-export.sql");
    }
    @Test void separateExplicitExportsHaveDistinctReceipts() throws Exception {
        var run=fixture.begin(fixture.alice,"owned");fixture.capture(run,"call","fact");var workers=Executors.newFixedThreadPool(2);
        try {
            var first=workers.submit(()->exports.export(fixture.alice,run.id(),true));var second=workers.submit(()->exports.export(fixture.alice,run.id(),true));
            assertThat(first.get(5,TimeUnit.SECONDS).exportId()).isNotEqualTo(second.get(5,TimeUnit.SECONDS).exportId());assertThat(audits()).isEqualTo(2);
        } finally {workers.shutdownNow();}
    }
}
