package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.system.support.OperationsMySqlFixture;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import java.time.LocalDateTime;
import java.util.UUID;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@EnabledIfSystemProperty(named="doorhandle.operations.source.config",matches=".+")
class OperationsCopyMySqlTest {
    OperationsMySqlFixture fixture;JdbcTemplate source,target;String delivery;
    @BeforeEach void setup() throws Exception {
        fixture=new OperationsMySqlFixture(true);source=fixture.source();target=fixture.target();delivery=UUID.randomUUID().toString();
        source.update("INSERT INTO operations_audit(id,actor_user_id,scope,domain,action,resource_id,request_id,result,resource_version,created_at) "
                + "VALUES(91,1,'PRIVATE',?,'UPDATE',?,?,?,-7,'2025-01-02 03:04:05.123456')","d".repeat(48),"r".repeat(160),"q".repeat(128),"x".repeat(40));
        source.update("INSERT INTO operations_file_delivery(id,delivery_id,actor_user_id,scope,domain,resource_id,file_id,correlation_id,resource_version,expected_bytes,accepted_bytes_lower_bound,http_status,state,revision,created_at,updated_at) "
                + "VALUES(92,?,1,'PRIVATE','DETECTION','report-one',NULL,'correlation-one',-9,NULL,17,NULL,'UNKNOWN',4,'2025-01-02 03:04:05.123456','2025-01-02 03:19:05.654321')",delivery);
    }
    @AfterEach void close() throws Exception {if(fixture!=null)fixture.close();}
    @Test void copiesAllOriginalFieldsAndReplaysTheOriginalSixPartReceipt() throws Exception {
        fixture.migrate("+08:00");
        var json=new com.fasterxml.jackson.databind.ObjectMapper();
        var audit=json.readTree(target.queryForObject("SELECT payload_json FROM audit_event WHERE kind='OPERATIONS'",String.class));
        assertThat(audit.path("legacyId").asText()).isEqualTo("91");assertThat(audit.path("resourceVersion").asLong()).isEqualTo(-7);
        assertThat(audit.path("legacyCreatedAt").asText()).isEqualTo("2025-01-02 03:04:05.123456");
        var payload=json.readTree(target.queryForObject("SELECT payload_json FROM workflow_instance WHERE kind='FILE_DELIVERY'",String.class));
        assertThat(payload.path("deliveryMode").asText()).isEqualTo("UNKNOWN");assertThat(payload.path("acceptedBytesLowerBound").asLong()).isEqualTo(17);
        assertThat(payload.path("expectedBytes").isNull()).isTrue();assertThat(payload.path("fileId").isNull()).isTrue();
        assertThat(payload.path("resourceVersion").asLong()).isEqualTo(-9);
        assertThat(target.queryForObject("SELECT CAST(created_at AS CHAR) FROM workflow_instance WHERE kind='FILE_DELIVERY'",String.class)).isEqualTo("2025-01-01 19:04:05.123456");
        assertThat(target.queryForObject("SELECT finished_at FROM workflow_instance WHERE kind='FILE_DELIVERY'",String.class)).isNull();
        var users=mock(BusinessUserDirectory.class);when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",false));
        var service=new OperationsAuditService(target,users);var actor=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);
        var tx=new TransactionTemplate(new DataSourceTransactionManager(fixture.dataSource()));
        tx.executeWithoutResult(status->service.append(new OperationsAuditApi.Event(actor,"PRIVATE","d".repeat(48),"UPDATE","r".repeat(160),"q".repeat(128),"x".repeat(40),-7L)));
        assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='OPERATIONS'",Long.class)).isEqualTo(1L);
        assertThat(service.list(actor,Long.MAX_VALUE,10,null).get(0).get("created_at")).isEqualTo(LocalDateTime.parse("2025-01-02T03:04:05.123456"));
        assertThat(source.queryForObject("SELECT COUNT(*) FROM operations_audit",Long.class)).isEqualTo(1L);
    }
    @Test void changedSourceCollationOrUnknownColumnCannotBeSilentlyAccepted() {
        source.execute("ALTER TABLE operations_file_delivery MODIFY COLUMN domain VARCHAR(48) COLLATE utf8mb4_bin NOT NULL");
        assertThatThrownBy(()->fixture.migrate("+08:00")).isInstanceOf(Exception.class);assertEmpty();
    }
    @Test void unknownSourceColumnIsRejected() {
        source.execute("ALTER TABLE operations_audit ADD COLUMN unreviewed_field TEXT NULL");
        assertThatThrownBy(()->fixture.migrate("+08:00")).isInstanceOf(Exception.class);assertEmpty();
    }
    @Test void missingPayloadFieldAfterCopyRollsBackBothKinds() throws Exception {
        fixture.install("CREATE TRIGGER fixture_corrupt_delivery BEFORE INSERT ON workflow_instance FOR EACH ROW SET NEW.payload_json=JSON_REMOVE(NEW.payload_json,'$.acceptedBytesLowerBound');",";");
        assertThatThrownBy(()->fixture.migrate("+08:00")).isInstanceOf(Exception.class);assertEmpty();
        assertThat(source.queryForObject("SELECT accepted_bytes_lower_bound FROM operations_file_delivery",Long.class)).isEqualTo(17L);
    }
    @Test void trailingSpaceInEitherProvenanceDiscriminatorIsRejected() throws Exception {
        for(String table:java.util.List.of("audit_event","workflow_instance")) {
            fixture.install("CREATE TRIGGER fixture_source_space BEFORE INSERT ON "+table+" FOR EACH ROW SET NEW.legacy_source=CONCAT(NEW.legacy_source,' ');",";");
            try {assertThatThrownBy(()->fixture.migrate("+08:00")).isInstanceOf(Exception.class);assertEmpty();}
            finally {target.execute("DROP TRIGGER fixture_source_space");}
        }
    }
    @Test void completedStateKeepsItsLastObservedTimeAndUnknownMode() throws Exception {
        source.update("UPDATE operations_audit SET resource_version=NULL WHERE id=91");
        source.update("UPDATE operations_file_delivery SET state='INTERRUPTED',http_status=500 WHERE id=92");fixture.migrate("+08:00");
        assertThat(target.queryForObject("SELECT JSON_TYPE(JSON_EXTRACT(payload_json,'$.resourceVersion')) FROM audit_event WHERE kind='OPERATIONS'",String.class)).isEqualTo("NULL");
        assertThat(target.queryForObject("SELECT CAST(finished_at AS CHAR) FROM workflow_instance WHERE kind='FILE_DELIVERY'",String.class)).isEqualTo("2025-01-01 19:19:05.654321");
        assertThat(target.queryForObject("SELECT JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.deliveryMode')) FROM workflow_instance WHERE kind='FILE_DELIVERY'",String.class)).isEqualTo("UNKNOWN");
    }
    @ParameterizedTest
    @CsvSource({"operations_audit,created_at,1960-01-02T03:04:05.123456", "operations_audit,created_at,9999-01-02T03:04:05.123456",
            "operations_file_delivery,created_at,1960-01-02T03:04:05.123456", "operations_file_delivery,created_at,9999-01-02T03:04:05.123456",
            "operations_file_delivery,updated_at,1960-01-02T03:04:05.123456", "operations_file_delivery,updated_at,9999-01-02T03:04:05.123456"})
    void unchangedOutOfRangeTimesCannotBecomeUtc(String table,String column,String original) {
        var value=LocalDateTime.parse(original);
        source.update("UPDATE "+table+" SET "+column+"=?",value);
        assertThatThrownBy(()->fixture.migrate("+08:00")).isInstanceOf(Exception.class);
        assertEmpty();
        assertThat(source.queryForObject("SELECT "+column+" FROM "+table,LocalDateTime.class)).isEqualTo(value);
    }
    @ParameterizedTest @ValueSource(strings={"+00:00","-05:30"})
    void explicitOffsetsPreserveEveryTimestampAndMicroseconds(String offset) throws Exception {
        fixture.migrate(offset);
        long shift=java.time.ZoneOffset.of(offset).getTotalSeconds();
        var created=LocalDateTime.parse("2025-01-02T03:04:05.123456").minusSeconds(shift);
        var updated=LocalDateTime.parse("2025-01-02T03:19:05.654321").minusSeconds(shift);
        assertThat(target.queryForObject("SELECT occurred_at FROM audit_event WHERE kind='OPERATIONS'",LocalDateTime.class)).isEqualTo(created);
        assertThat(target.queryForObject("SELECT created_at FROM workflow_instance WHERE kind='FILE_DELIVERY'",LocalDateTime.class)).isEqualTo(created);
        assertThat(target.queryForObject("SELECT updated_at FROM workflow_instance WHERE kind='FILE_DELIVERY'",LocalDateTime.class)).isEqualTo(updated);
    }
    @ParameterizedTest @ValueSource(strings={"audit_event","workflow_instance"})
    void unrelatedPublicFieldsCannotBeInjectedIntoCopiedFacts(String table) throws Exception {
        String mutation=table.equals("audit_event")?"NEW.quantity=17,NEW.unit='BYTES'":"NEW.error_code='INJECTED'";
        fixture.install("CREATE TRIGGER fixture_extra_state BEFORE INSERT ON "+table+" FOR EACH ROW SET "+mutation+";",";");
        assertThatThrownBy(()->fixture.migrate("+08:00")).isInstanceOf(Exception.class);
        assertEmpty();
        assertThat(source.queryForObject("SELECT COUNT(*) FROM operations_audit",Long.class)).isEqualTo(1L);
        assertThat(source.queryForObject("SELECT COUNT(*) FROM operations_file_delivery",Long.class)).isEqualTo(1L);
    }
    private void assertEmpty() {
        assertThat(target.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='OPERATIONS'",Long.class)).isZero();
        assertThat(target.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='FILE_DELIVERY'",Long.class)).isZero();
    }
}
