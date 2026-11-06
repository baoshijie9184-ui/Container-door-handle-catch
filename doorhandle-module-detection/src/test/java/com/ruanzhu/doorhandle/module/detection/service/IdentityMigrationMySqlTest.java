package com.ruanzhu.doorhandle.module.detection.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.detection.support.IdentityMigrationMySqlFixture;
import java.time.LocalDateTime;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import static org.assertj.core.api.Assertions.*;

/** Actual eleven-table source -> complete compact model; requires two admitted disposable ECS schemas. */
@EnabledIfSystemProperty(named="detection.identity.source.config",matches=".+")
class IdentityMigrationMySqlTest {
    private static final LocalDateTime WALL=LocalDateTime.of(2026,2,3,14,15,16,123456000);
    private static final String TASK="缺名😀 ";
    IdentityMigrationMySqlFixture fixture;
    JdbcTemplate source,target;
    @BeforeEach void setup() throws Exception {
        fixture=new IdentityMigrationMySqlFixture();source=fixture.source();target=fixture.target();seed();
    }
    @AfterEach void close() throws Exception {if(fixture!=null)fixture.close();}

    @Test void allOriginalFieldsClocksUnsignedCursorsAndOrphanHeadsSurviveWithoutInventingTasks() throws Exception {
        long high=source.queryForObject("SELECT auto_increment FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='detection_identity_mapping_item'",Long.class);
        fixture.copy();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE'",Integer.class)).isEqualTo(29);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM detection_task",Integer.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='IDENTITY_MIGRATION_CLOCK'",Integer.class)).isEqualTo(11);
        assertThat(target.queryForObject("SELECT CAST(identity_source_id AS CHAR) FROM workflow_instance WHERE kind='DETECTION_IDENTITY_MAP_ITEM'",String.class)).isEqualTo("9007199254740993");
        assertThat(target.queryForObject("SELECT created_at FROM workflow_instance WHERE kind='DETECTION_IDENTITY_MAP_ITEM'",String.class)).isNull();
        assertThat(target.queryForObject("SELECT updated_at FROM workflow_instance WHERE kind='DETECTION_IDENTITY_MAP_ITEM'",String.class)).isNull();
        assertThat(target.queryForObject("SELECT occurred_at FROM audit_event WHERE kind='DETECTION_IDENTITY_RECON_ITEM'",String.class)).isNull();
        assertThat(target.queryForObject("SELECT created_at FROM workflow_instance WHERE kind='DETECTION_IDENTITY_COMMAND'",LocalDateTime.class)).isEqualTo(WALL.minusHours(8));
        assertThat(target.queryForObject("SELECT JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.legacyCreatedAt')) FROM workflow_instance WHERE kind='DETECTION_IDENTITY_COMMAND'",String.class)).isEqualTo("2026-02-03 14:15:16.123456");
        assertThat(target.queryForObject("SELECT JSON_TYPE(JSON_EXTRACT(payload_json,'$.originalName')) FROM audit_event WHERE kind='DETECTION_IDENTITY_MISSING_NAME'",String.class)).isEqualTo("NULL");
        var store=new DetectionIdentityPersistence(target,new ObjectMapper());
        var head=store.head("缺名😀","created",false).get(0);
        assertThat(((Number)head.get("event_id")).longValue()).isEqualTo(71);
        assertThat(store.head("orphan-task","created",false).get(0).get("event_id")).isNull();
        assertThat(target.queryForObject("SELECT JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.legacyEventId')) FROM runtime_state WHERE namespace='DETECTION_IDENTITY_BINDING' AND identity_task_id='orphan-task'",String.class)).isEqualTo("999999");
        assertThat(source.queryForObject("SELECT auto_increment FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='detection_identity_mapping_item'",Long.class)).isEqualTo(high);
        assertThat(target.queryForObject("SELECT auto_increment FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='workflow_instance'",Long.class)).isGreaterThanOrEqualTo(high);
    }

    @Test void originalPadSpaceEqualityAndOriginalTaskBytesRemainDistinctRequirements() throws Exception {
        fixture.copy();
        assertThat(DetectionIdentityPersistence.identityScope(TASK,"created "))
                .isEqualTo(DetectionIdentityPersistence.identityScope("缺名😀","created"));
        assertThat(target.queryForObject("SELECT identity_task_id FROM runtime_state WHERE namespace='DETECTION_IDENTITY_BINDING' AND identity_task_id=?",String.class,"缺名😀")).isEqualTo(TASK);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM ("+DetectionIdentityPersistence.EVENTS+") e WHERE e.task_id=? AND e.identity_role='created'",Integer.class,"缺名😀")).isEqualTo(1);
    }

    @Test void unreviewedOriginalColumnFailsBeforeAnyIdentityRowsAreCopied() throws Exception {
        source.execute("ALTER TABLE detection_identity_command ADD COLUMN unreviewed VARCHAR(20) NULL");
        assertThatThrownBy(fixture::copy).isInstanceOf(Exception.class);assertEmpty();
        assertThat(source.queryForObject("SELECT COUNT(*) FROM detection_identity_command",Integer.class)).isEqualTo(1);
    }

    @Test void unsupportedTimezoneRangeFailsRatherThanRelabelingTheUnchangedHistoricalTime() throws Exception {
        source.update("UPDATE detection_identity_command SET created_at='1800-01-01 10:00:00.000001'");
        assertThatThrownBy(fixture::copy).isInstanceOf(Exception.class);assertEmpty();
    }

    @Test void repeatedCopyRetainsPriorFactsAndImportedEvidenceIsImmutable() throws Exception {
        fixture.copy();
        int events=target.queryForObject("SELECT COUNT(*) FROM audit_event",Integer.class);
        assertThatThrownBy(fixture::copy).isInstanceOf(Exception.class);
        assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event",Integer.class)).isEqualTo(events);
        assertThatThrownBy(()->target.update("UPDATE audit_event SET payload_json=JSON_SET(payload_json,'$.actorName','changed') WHERE kind='DETECTION_IDENTITY_BINDING_EVENT'"))
                .isInstanceOf(DataAccessException.class);
    }

    private void assertEmpty() {
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind IN ('DETECTION_IDENTITY_COMMAND','DETECTION_IDENTITY_MAP_BATCH','DETECTION_IDENTITY_MAP_ITEM','DETECTION_IDENTITY_REPORT')",Integer.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM runtime_state WHERE namespace LIKE 'DETECTION_IDENTITY_%'",Integer.class)).isZero();
    }
    private void seed() throws Exception {
        source.update("INSERT INTO detection_identity_control VALUES(1,'PREVIEW',1)");
        source.update("INSERT INTO detection_identity_source_control VALUES(1,'COLLECTING',NULL)");
        source.update("INSERT INTO detection_identity_command VALUES('activate',99,?,?,?)","a".repeat(64),"{\"revision\":1}",WALL);
        String result=new ObjectMapper().writeValueAsString(Map.of("requestId","map-1","applied",1,"revision",1,"digest","a".repeat(64),"protocol","identity-map-v3","missingNameCount",1));
        source.update("INSERT INTO detection_identity_mapping_batch VALUES(9,'map-1',99,'boss',?,0,1,1,?,?)","a".repeat(64),result,WALL);
        source.update("INSERT INTO detection_identity_mapping_item VALUES(9007199254740993,9,?,'created','',?,NULL,NULL,99,'boss','SUPERVISOR',?,'SOURCE_RECORD_CHECKED')",TASK,"b".repeat(64),"f".repeat(64));
        source.execute("ALTER TABLE detection_identity_mapping_item AUTO_INCREMENT=9007199254741099");
        source.update("INSERT INTO detection_assignment_identity_event VALUES(61,'assigned-task',2,99,'boss',98,'worker',?,'assign-1',?)","f".repeat(64),WALL);
        source.update("INSERT INTO detection_identity_binding_event VALUES(71,?,'created',1,99,'',?,99,'boss','SUPERVISOR_MISSING_NAME','map-1',9,?,?,?)",TASK,"f".repeat(64),"0".repeat(64),"c".repeat(64),WALL);
        source.update("INSERT INTO detection_identity_binding VALUES(72,?,'created',71,1,?)",TASK,"c".repeat(64));
        source.update("INSERT INTO detection_identity_binding VALUES(73,'orphan-task','created',999999,2,?)","d".repeat(64));
        source.update("INSERT INTO detection_identity_missing_name_evidence VALUES(9,?,'created',NULL,?,99,'source:file-1',?)",TASK,"b".repeat(64),WALL);
        String summary="{\"protocol\":\"identity-reconciliation-v1\",\"label\":\"原文 null\"}";
        source.update("INSERT INTO detection_identity_reconciliation_report VALUES(81,'report-1',99,'boss',?,'identity-reconciliation-v1',1,'PREVIEW','COLLECTING',?,?,1,5,1,?,NULL,?)","e".repeat(64),WALL,WALL.plusNanos(1000),"e".repeat(64),summary);
        source.update("INSERT INTO detection_identity_reconciliation_item VALUES(82,81,'orphan-task','created','null',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,?,?)","[\"SOURCE_UNVERIFIED\"]","d".repeat(64));
    }
}
