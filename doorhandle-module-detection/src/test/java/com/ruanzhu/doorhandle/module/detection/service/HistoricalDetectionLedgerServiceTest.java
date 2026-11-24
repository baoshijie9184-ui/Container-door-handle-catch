package com.ruanzhu.doorhandle.module.detection.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.organization.EmployeeDirectoryApi;
import com.ruanzhu.doorhandle.contracts.organization.EmployeeDirectoryApi.EmployeeIdentity;
import com.ruanzhu.doorhandle.contracts.security.BusinessAccountLookupApi;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity;
import com.ruanzhu.doorhandle.module.detection.dto.detection.HistoricalDetectionLedger.Assigned;
import com.ruanzhu.doorhandle.module.detection.dto.detection.HistoricalDetectionLedger.Assignment;
import com.ruanzhu.doorhandle.module.detection.dto.detection.HistoricalDetectionLedger.Assignments;
import com.ruanzhu.doorhandle.module.detection.dto.detection.HistoricalDetectionLedger.Entry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

public class HistoricalDetectionLedgerServiceTest {
    private static final Identity SUPERVISOR = new Identity(19, "SUP-0001", true);
    private static final Identity OTHER_SUPERVISOR = new Identity(21, "SUP-0002", true);
    private static final Identity DETECTOR = new Identity(28, "DET-0001", false);
    private static final long LARGE_ID = 9_007_199_254_740_993L;
    private static final ObjectMapper JSON = new ObjectMapper();

    private JdbcTemplate jdbc;
    private TransactionTemplate tx;
    private BusinessUserDirectory users;
    private EmployeeDirectoryApi employees;
    private HistoricalDetectionLedgerService ledger;

    @BeforeEach void setUp() {
        var source = new DriverManagerDataSource("jdbc:h2:mem:ledger-" + UUID.randomUUID() + ";MODE=MySQL;DB_CLOSE_DELAY=-1", "sa", "");
        jdbc = new JdbcTemplate(source);
        tx = new TransactionTemplate(new DataSourceTransactionManager(source));
        users = mock(BusinessUserDirectory.class);
        employees = mock(EmployeeDirectoryApi.class);
        var accounts = mock(BusinessAccountLookupApi.class);
        when(users.authenticated()).thenReturn(SUPERVISOR);
        for (var account : List.of(SUPERVISOR, OTHER_SUPERVISOR, DETECTOR)) {
            when(accounts.findExactUserId(account.username())).thenReturn(account.userId());
            when(users.lockCurrent(account.userId(), account.username())).thenReturn(account);
        }
        when(employees.lock(2L)).thenReturn(new EmployeeIdentity(2L, "DET-0001", "检测员", "ACTIVE", "DETECTION", null, null));
        when(employees.lock(3L)).thenReturn(new EmployeeIdentity(3L, "EMP-0003", "现场检测员", "ACTIVE", "DETECTION", null, null));
        when(employees.lock(4L)).thenReturn(new EmployeeIdentity(4L, "EMP-0004", "已离岗检测员", "RESIGNED", "DETECTION", null, null));
        ledger = new HistoricalDetectionLedgerService(new NamedParameterJdbcTemplate(jdbc), users, accounts, employees, JSON);
        jdbc.execute("CREATE ALIAS JSON_EXTRACT FOR '" + getClass().getName() + ".jsonExtract'");
        jdbc.execute("CREATE ALIAS JSON_UNQUOTE FOR '" + getClass().getName() + ".jsonUnquote'");
        jdbc.execute("CREATE TABLE users(id BIGINT PRIMARY KEY, username VARCHAR(50), employee_id BIGINT, role VARCHAR(16), enabled TINYINT)");
        jdbc.execute("CREATE TABLE employee(id BIGINT PRIMARY KEY, employee_number VARCHAR(50), name VARCHAR(50),"
                + "status VARCHAR(20), employee_type VARCHAR(50))");
        jdbc.execute("CREATE TABLE model_management(model_id INT PRIMARY KEY, model_name VARCHAR(100))");
        jdbc.execute("""
                CREATE TABLE historical_detection_summary(id BIGINT PRIMARY KEY, model_id INT, detected_images_count INT,
                    start_time DATETIME, finished_at DATETIME, folder_path VARCHAR(255))
                """);
        jdbc.execute("""
                CREATE TABLE runtime_state(namespace VARCHAR(64), owner_id BIGINT, scope_key VARCHAR(160),
                    state_code VARCHAR(32), current_ref VARCHAR(180), payload_json VARCHAR(255),
                    actor_user_id BIGINT CHECK(actor_user_id IS NULL), created_at DATETIME(6),
                    updated_at DATETIME(6), PRIMARY KEY(namespace,owner_id,scope_key))
                """);
        jdbc.update("INSERT INTO users VALUES(19,'SUP-0001',1,'SUPERVISOR',1),(21,'SUP-0002',NULL,'SUPERVISOR',1),"
                + "(28,'DET-0001',2,'INSPECTOR',1),(29,'other-login',3,'OPERATOR',1)");
        jdbc.update("INSERT INTO employee VALUES(1,'SUP-0001','主管一','ACTIVE','SUPERVISOR'),"
                + "(2,'DET-0001','检测员','ACTIVE','DETECTION'),(3,'EMP-0003','现场检测员','ACTIVE','DETECTION'),"
                + "(4,'EMP-0004','已离岗检测员','RESIGNED','DETECTION')");
        jdbc.update("INSERT INTO model_management VALUES(3,'历史模型')");
        jdbc.update("""
                INSERT INTO historical_detection_summary VALUES
                    (1,3,100,'2024-01-01 08:00:00','2024-01-01 08:10:00',''),
                    (2,3,200,'2025-02-02 08:00:00','2025-02-02 08:20:00',''),
                    (?,NULL,NULL,'2025-02-02 08:00:00',NULL,'')
                """, LARGE_ID);
    }

    @Test void paginatesCurrentScopeAndPreservesLedgerDatesAndIdPrecision() {
        var page = ledger.list("all", 1, 2);
        assertThat(page.total()).isEqualTo(3);
        assertThat(page.records()).extracting(Entry::id).containsExactly(Long.toString(LARGE_ID), "2");
        assertThat(page.records().get(0).detectedImages()).isNull();
        assertThat(page.records().get(1).modelName()).isEqualTo("历史模型");
        assertThat(page.records().get(1).startTime()).isEqualTo(LocalDateTime.of(2025, 2, 2, 8, 0));
        assertThat(page.records()).allMatch(row -> row.supervisorUsername() == null
                && row.inspectorEmployeeNumber() == null && row.assignedAt() == null);
        assertThat(ledger.list("all", 2, 2).records()).extracting(Entry::id).containsExactly("1");
        assertThat(ledger.list("mine", 1, 20).total()).isZero();
        assertThatThrownBy(() -> ledger.list("other", 1, 20)).isInstanceOfSatisfying(BusinessException.class,
                error -> assertThat(error.getCode()).isEqualTo(400));
    }

    @Test void writesBothResponsibilitiesAndPreservesTimeAndWriterOnReplay() {
        var command = request(row("1", "SUP-0002", "EMP-0003"), row("2", "SUP-0001", "DET-0001"));
        var originalLedger = jdbc.queryForList("SELECT * FROM historical_detection_summary ORDER BY id");
        assertThat(assign(command)).isEqualTo(new Assigned(2, 0, 2));
        verify(employees).lock(2L);
        verify(employees).lock(3L);
        var inserted = jdbc.queryForList("SELECT * FROM runtime_state ORDER BY scope_key");
        assertThat(assign(command)).isEqualTo(new Assigned(0, 2, 2));
        assertThat(jdbc.queryForList("SELECT * FROM runtime_state ORDER BY scope_key")).isEqualTo(inserted);
        assertThat(jdbc.queryForList("SELECT * FROM historical_detection_summary ORDER BY id")).isEqualTo(originalLedger);
        assertThat(jdbc.queryForList("SELECT payload_json FROM runtime_state ORDER BY scope_key", String.class))
                .containsExactly("{\"inspectorEmployeeId\":\"3\",\"actorUserId\":\"19\"}",
                        "{\"inspectorEmployeeId\":\"2\",\"actorUserId\":\"19\"}");

        when(users.authenticated()).thenReturn(OTHER_SUPERVISOR);
        var supervisorRow = ledger.list("mine", 1, 20).records().get(0);
        assertThat(supervisorRow.id()).isEqualTo("1");
        assertThat(supervisorRow.supervisorName()).isNull();
        assertThat(supervisorRow.inspectorName()).isEqualTo("现场检测员");
        assertThat(supervisorRow.inspectorUsername()).isNull();
        assertThat(supervisorRow.assignedAt().getOffset()).isEqualTo(ZoneOffset.UTC);

        when(users.authenticated()).thenReturn(DETECTOR);
        var detectorRows = ledger.list("mine", 1, 20).records();
        assertThat(detectorRows).extracting(Entry::id).containsExactly("2");
        assertThat(detectorRows.get(0).inspectorName()).isEqualTo("检测员");
        assertThat(detectorRows.get(0).inspectorUsername()).isEqualTo("DET-0001");
        jdbc.update("UPDATE users SET enabled=0 WHERE id=28");
        assertThat(ledger.list("mine", 1, 20).total()).isZero();
        jdbc.update("UPDATE users SET enabled=1 WHERE id=28");
        jdbc.update("UPDATE users SET employee_id=NULL WHERE id=29");
        jdbc.update("UPDATE users SET employee_id=3 WHERE id=28");
        assertThat(ledger.list("mine", 1, 20).records()).extracting(Entry::id).containsExactly("1");
        jdbc.update("UPDATE users SET employee_id=NULL WHERE id=28");
        assertThat(ledger.list("mine", 1, 20).total()).isZero();
        assertThatThrownBy(() -> ledger.list("all", 1, 20)).isInstanceOfSatisfying(BusinessException.class,
                error -> assertThat(error.getCode()).isEqualTo(403));
        assertThatThrownBy(() -> assign(command)).isInstanceOfSatisfying(BusinessException.class,
                error -> assertThat(error.getCode()).isEqualTo(403));
    }

    @Test void conflictingPairOrIneligiblePersonLeavesWholeBatchUnchanged() {
        assertThat(assign(request(row("2", "SUP-0002", "DET-0001")))).isEqualTo(new Assigned(1, 0, 1));
        assertThatThrownBy(() -> assign(request(row("1", "SUP-0001", "DET-0001"), row("2", "SUP-0002", "EMP-0003"))))
                .isInstanceOfSatisfying(BusinessException.class, error -> assertThat(error.getCode()).isEqualTo(409));
        assertThat(jdbc.queryForList("SELECT scope_key FROM runtime_state", String.class)).containsExactly("2");

        doThrow(new SecurityException("disabled")).when(users).lockCurrent(21, "SUP-0002");
        assertThatThrownBy(() -> assign(request(row("1", "SUP-0001", "DET-0001"), row(Long.toString(LARGE_ID), "SUP-0002", "DET-0001"))))
                .isInstanceOfSatisfying(BusinessException.class, error -> assertThat(error.getCode()).isEqualTo(400));
        assertThatThrownBy(() -> assign(request(row("1", "DET-0001", "EMP-0003"))))
                .isInstanceOfSatisfying(BusinessException.class, error -> assertThat(error.getCode()).isEqualTo(400));
        assertThatThrownBy(() -> assign(request(row("1", "SUP-0001", "EMP-0004"))))
                .isInstanceOfSatisfying(BusinessException.class, error -> assertThat(error.getCode()).isEqualTo(400));
        assertThat(jdbc.queryForList("SELECT scope_key FROM runtime_state", String.class)).containsExactly("2");
    }

    @Test void retainsLegacySingleRecipientWithoutProjectingItAsAPair() {
        jdbc.update("INSERT INTO runtime_state(namespace, owner_id, scope_key, state_code, current_ref, payload_json) "
                + "VALUES('HISTORICAL_LEDGER_ASSIGNMENT',0,'1','ASSIGNED','19','{\"actorUserId\":\"19\"}')");
        var legacy = jdbc.queryForMap("SELECT * FROM runtime_state");
        assertThat(ledger.list("mine", 1, 20).total()).isZero();
        assertThat(ledger.list("all", 1, 20).records()).allMatch(row -> row.supervisorUsername() == null);
        assertThat(assign(request(row("1", "SUP-0002", "EMP-0003")))).isEqualTo(new Assigned(1, 0, 1));
        assertThat(jdbc.queryForMap("SELECT * FROM runtime_state WHERE namespace='HISTORICAL_LEDGER_ASSIGNMENT'")).isEqualTo(legacy);
        assertThat(ledger.list("all", 1, 20).records()).filteredOn(row -> row.id().equals("1"))
                .extracting(Entry::supervisorUsername).containsExactly("SUP-0002");
    }

    @Test void rollsBackEarlierInsertIfPersistenceFailsInsideBatch() {
        jdbc.execute("ALTER TABLE runtime_state ADD CONSTRAINT reject_second CHECK(scope_key <> '2')");
        assertThatThrownBy(() -> assign(request(row("1", "SUP-0002", "EMP-0003"), row("2", "SUP-0001", "DET-0001"))))
                .isInstanceOf(DataIntegrityViolationException.class);
        assertThat(jdbc.queryForList("SELECT scope_key FROM runtime_state", String.class)).isEmpty();
    }

    @Test void rejectsNonStringOutOfRangeAndDuplicateLedgerIds() {
        var badIds = List.of(new Assignment(JsonNodeFactory.instance.numberNode(1), "SUP-0002", "DET-0001"),
                row("9223372036854775808", "SUP-0002", "DET-0001"), row("01", "SUP-0002", "DET-0001"));
        for (var bad : badIds) {
            assertThatThrownBy(() -> assign(request(bad))).isInstanceOfSatisfying(BusinessException.class,
                    error -> assertThat(error.getCode()).isEqualTo(400));
        }
        assertThatThrownBy(() -> assign(request(row("1", "SUP-0002", "DET-0001"), row("1", "SUP-0002", "DET-0001"))))
                .isInstanceOfSatisfying(BusinessException.class, error -> assertThat(error.getCode()).isEqualTo(400));
        assertThatThrownBy(() -> assign(request(row("1", "SUP-0002", "DET-0001"), row("999", "SUP-0002", "DET-0001"))))
                .isInstanceOfSatisfying(BusinessException.class, error -> assertThat(error.getCode()).isEqualTo(404));
        assertThatThrownBy(() -> assign(request(row("1", "SUP-0002", null))))
                .isInstanceOfSatisfying(BusinessException.class, error -> assertThat(error.getCode()).isEqualTo(400));
        assertThat(jdbc.queryForList("SELECT scope_key FROM runtime_state", String.class)).isEmpty();
    }

    private Assigned assign(Assignments assignments) {
        return tx.execute(status -> ledger.assign(assignments));
    }

    private static Assignments request(Assignment... assignments) {
        return new Assignments(List.of(assignments));
    }

    private static Assignment row(String id, String supervisor, String inspectorNumber) {
        return new Assignment(JsonNodeFactory.instance.textNode(id), supervisor, inspectorNumber);
    }

    // H2's fixture bridges the two MySQL JSON operations used by the production queries.
    public static String jsonExtract(String document, String path) throws Exception {
        if (document == null) return null;
        var value = JSON.readTree(document).get(path.substring(2));
        return value == null ? null : value.toString();
    }

    public static String jsonUnquote(String value) throws Exception {
        return value == null ? null : JSON.readTree(value).asText();
    }
}
