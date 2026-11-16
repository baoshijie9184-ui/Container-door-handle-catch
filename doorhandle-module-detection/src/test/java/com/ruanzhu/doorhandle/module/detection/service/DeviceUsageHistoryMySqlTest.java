package com.ruanzhu.doorhandle.module.detection.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.extension.spring.MybatisSqlSessionFactoryBean;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.framework.config.MybatisPlusConfig;
import com.ruanzhu.doorhandle.module.detection.support.CoreCopyMySqlFixture;
import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.entity.DeviceUsageRecord;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceMapper;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceUsageRecordMapper;
import com.ruanzhu.doorhandle.module.device.mapper.EmployeeMapper;
import com.ruanzhu.doorhandle.module.device.service.DeviceMutationParticipant;
import com.ruanzhu.doorhandle.module.device.service.impl.DeviceUsageRecordServiceImpl;
import com.ruanzhu.doorhandle.module.device.service.impl.DeviceServiceImpl;
import com.ruanzhu.doorhandle.module.device.service.impl.EmployeeServiceImpl;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceCaptureAlertMapper;
import com.ruanzhu.doorhandle.module.device.service.DeviceUsageRecordService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.api.parallel.Execution;
import org.junit.jupiter.api.parallel.ExecutionMode;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.support.TransactionTemplate;

import java.sql.SQLException;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Real compact DDL, MyBatis handlers and transaction locks; shares the admitted core-copy fixture protocol. */
@EnabledIfSystemProperty(named="doorhandle.core.copy.source.config",matches=".+")
@Execution(ExecutionMode.SAME_THREAD)
class DeviceUsageHistoryMySqlTest {
    private CoreCopyMySqlFixture fixture;
    private JdbcTemplate jdbc;
    private TransactionTemplate tx;
    private DeviceUsageRecordServiceImpl service;
    private DeviceMutationParticipant participant;
    private DeviceServiceImpl devices;
    private EmployeeServiceImpl employees;
    private final AgentActor actor = new AgentActor(1, "supervisor", AgentActor.Role.SUPERVISOR);

    @BeforeEach void setup() throws Exception {
        fixture = new CoreCopyMySqlFixture();
        jdbc = fixture.target();
        fixture.copyChatReferenceAndInstallRelations();
        var config = new MybatisConfiguration(); config.setMapUnderscoreToCamelCase(true);
        config.addMapper(EmployeeMapper.class); config.addMapper(DeviceMapper.class); config.addMapper(DeviceUsageRecordMapper.class);
        var factory = new MybatisSqlSessionFactoryBean(); factory.setDataSource(jdbc.getDataSource()); factory.setConfiguration(config);
        // Match the application: @Version updates require the optimistic-lock plugin.
        factory.setPlugins(new MybatisPlusConfig().mybatisPlusInterceptor());
        factory.setMapperLocations(new ClassPathResource("mapper/DeviceUsageRecordMapper.xml"));
        var sql = new SqlSessionTemplate(factory.getObject());
        service = new DeviceUsageRecordServiceImpl();
        ReflectionTestUtils.setField(service, "baseMapper", sql.getMapper(DeviceUsageRecordMapper.class));
        ReflectionTestUtils.setField(service, "deviceUsageRecordMapper", sql.getMapper(DeviceUsageRecordMapper.class));
        ReflectionTestUtils.setField(service, "employeeMapper", sql.getMapper(EmployeeMapper.class));
        ReflectionTestUtils.setField(service, "deviceMapper", sql.getMapper(DeviceMapper.class));
        devices = new DeviceServiceImpl(sql.getMapper(DeviceMapper.class), mock(DeviceCaptureAlertMapper.class), service);
        employees = new EmployeeServiceImpl();
        ReflectionTestUtils.setField(employees, "employeeMapper", sql.getMapper(EmployeeMapper.class));
        ReflectionTestUtils.setField(employees, "deviceMapper", sql.getMapper(DeviceMapper.class));
        ReflectionTestUtils.setField(employees, "deviceUsageRecordService", service);
        tx = new TransactionTemplate(new DataSourceTransactionManager(jdbc.getDataSource()));
        var users = mock(BusinessUserDirectory.class);
        when(users.current(1, "supervisor")).thenReturn(new BusinessUserDirectory.Identity(1, "supervisor", true));
        participant = new DeviceMutationParticipant(jdbc, users);
        jdbc.update("INSERT INTO employee(id,name,employee_number,hire_date) VALUES(11,'Current employee','E11','2020年春')");
        jdbc.update("INSERT INTO device_management(id,device_code,employee_id,status) VALUES(9,'Current device',11,'IN_USE')");
        jdbc.update("INSERT INTO device_usage(id,device_id,employee_id,device_code,device_type,model_name,serial_number,employee_name,employee_number,contact,status,start_time,remarks) "
                + "VALUES(41,9,11,'Original device','DETECTION','Original model','Original serial','Original employee','Original number','Original contact','IN_USE','2020-01-01','Original note')");
    }

    @AfterEach void close() throws Exception { if (fixture != null) fixture.close(); }

    @Test void joinedDeviceReadsKeepTheAssignmentIdAlongsideTheNestedEmployee() {
        assertAssignedDeviceRead(devices.getDeviceById(9L));
        assertThat(devices.getAllDevicesWithEmployee()).singleElement().satisfies(this::assertAssignedDeviceRead);
        var page = devices.getDevicesByPage(null, null, null, null, null, 1, 10);
        assertThat(page.get("total")).isEqualTo(1L);
        assertThat((List<?>) page.get("records")).singleElement().satisfies(row -> assertAssignedDeviceRead((Device) row));

        assertThat(tx.<Boolean>execute(status -> devices.removeEmployeeFromDevice(9L))).isTrue();
        assertThat(devices.getDeviceById(9L).getEmployeeId()).isNull();
        assertThat(devices.getDeviceById(9L).getEmployee()).isNull();
        assertThat(devices.getAllDevicesWithEmployee()).singleElement().satisfies(device -> {
            assertThat(device.getEmployeeId()).isNull();
            assertThat(device.getEmployee()).isNull();
        });
    }

    @Test void productionOptimisticLockRejectsAStaleDeviceVersionWithoutChangingItsAssignment() {
        Device current = devices.getDeviceById(9L);
        Device stale = devices.getDeviceById(9L);
        assertThat(current.getVersion()).isZero();
        current.setStatus("MAINTENANCE");
        Device updated = tx.execute(status -> devices.updateDevice(9L, current));
        assertThat(updated.getVersion()).isEqualTo(1);
        stale.setStatus("IDLE");
        assertThatThrownBy(() -> tx.executeWithoutResult(status -> devices.updateDevice(9L, stale)))
                .isInstanceOfSatisfying(BusinessException.class, conflict -> assertThat(conflict.getCode()).isEqualTo(409));
        assertThat(devices.getDeviceById(9L)).satisfies(device -> {
            assertThat(device.getVersion()).isEqualTo(1);
            assertThat(device.getStatus()).isEqualTo("MAINTENANCE");
            assertThat(device.getEmployeeId()).isEqualTo(11L);
        });
    }

    @Test void deletingParentsPreservesStoredHistoryAndAllowsReadsNotesAndHistoricalReturn() {
        Map<String,Object> before = jdbc.queryForMap("SELECT * FROM device_usage WHERE id=41");
        var originalSnapshot = tx.execute(status -> participant.capture(actor, "DEVICE_USAGE", "updateRecord", "41", true));
        jdbc.update("DELETE FROM employee WHERE id=11");
        jdbc.update("DELETE FROM device_management WHERE id=9");
        assertThat(jdbc.queryForMap("SELECT * FROM device_usage WHERE id=41")).isEqualTo(before);
        var afterSnapshot = tx.execute(status -> participant.capture(actor, "DEVICE_USAGE", "updateRecord", "41", true));
        assertThat(afterSnapshot.fields()).isEqualTo(originalSnapshot.fields());
        assertThat(service.getById(41L).getEmployeeName()).isEqualTo("Original employee");
        assertThat(service.getDeviceUsageRecordsByDeviceId(9L)).hasSize(1);
        assertThat(service.getDeviceUsageRecords(1, 10, 9L, null, null, null, null, null, null).get("total")).isEqualTo(1);
        DeviceUsageRecord update = service.getById(41L); update.setRemarks("Historical note corrected");
        tx.executeWithoutResult(status -> service.updateDeviceUsageRecord(update));
        assertThat(service.getById(41L).getRemarks()).isEqualTo("Historical note corrected");
        assertThat(tx.<Boolean>execute(status -> service.returnDevice(41L, "Historical return"))).isTrue();
        DeviceUsageRecord returned = service.getById(41L);
        assertThat(returned.getDeviceId()).isEqualTo(9L); assertThat(returned.getEmployeeId()).isEqualTo(11L);
        assertThat(returned.getEmployeeName()).isEqualTo("Original employee"); assertThat(returned.getDeviceCode()).isEqualTo("Original device");
        assertThat(returned.getStatus()).isEqualTo("RETURNED"); assertThat(returned.getEndTime()).isNotNull();
    }

    @Test void newAndChangedReferencesRequireRealParentsAndHoldSharedLocksUntilCommit() {
        tx.executeWithoutResult(status -> {
            DeviceUsageRecord created = new DeviceUsageRecord(); created.setDeviceId(9L); created.setEmployeeId(11L);
            assertThat(service.createRecord(created)).isTrue();
            assertBlockedConcurrentWrite("UPDATE employee SET name='Concurrent change' WHERE id=11");
            assertBlockedConcurrentWrite("UPDATE device_management SET device_code='Concurrent change' WHERE id=9");
        });
        DeviceUsageRecord invalid = new DeviceUsageRecord(); invalid.setEmployeeId(999L); invalid.setDeviceId(9L);
        assertThatThrownBy(() -> tx.executeWithoutResult(status -> service.createRecord(invalid))).isInstanceOf(BusinessException.class);
        DeviceUsageRecord invalidDevice = new DeviceUsageRecord(); invalidDevice.setEmployeeId(11L); invalidDevice.setDeviceId(999L);
        assertThatThrownBy(() -> tx.executeWithoutResult(status -> service.createDeviceUsageRecord(invalidDevice))).isInstanceOf(BusinessException.class);
        DeviceUsageRecord changed = new DeviceUsageRecord(); changed.setId(41L); changed.setDeviceId(999L);
        assertThatThrownBy(() -> tx.executeWithoutResult(status -> service.updateRecord(changed))).isInstanceOf(BusinessException.class);
        assertThat(service.getById(41L).getDeviceId()).isEqualTo(9L);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM device_usage", Integer.class)).isEqualTo(2);
    }

    @Test void oldReceiptsCannotReleaseTheSameEmployeesNewAssignmentAndCurrentReturnIsIdempotent() {
        jdbc.update("INSERT INTO device_usage(id,device_id,employee_id,status,start_time,end_time) VALUES(42,9,11,'RETURNED','2021-01-01','2021-01-02')");
        var closedLatest = tx.execute(status -> participant.related(actor, "DEVICE", "USAGE_RETURN", "9", new Object[]{9L, "Return"}, List.of(), true));
        assertThat(closedLatest).extracting(item -> item.resourceId()).containsExactly("42");
        assertThat(tx.<Boolean>execute(status -> service.updateRecordOnUnassign(9L, "Do not reopen old history"))).isFalse();
        assertThat(service.getById(41L).getStatus()).isEqualTo("IN_USE");
        assertThat(service.getById(42L).getEndTime()).isNotNull();
        jdbc.update("UPDATE device_usage SET status='RETURNED',end_time='2020-01-02' WHERE id=41");
        jdbc.update("UPDATE device_usage SET status='IN_USE',end_time=NULL WHERE id=42");
        var originalEnd = service.getById(41L).getEndTime();
        assertThat(tx.<Boolean>execute(status -> service.returnDevice(41L, "Repeated return"))).isTrue();
        assertThat(service.getById(41L).getEndTime()).isEqualTo(originalEnd);
        assertLiveAssignment();
        // A residual old open row must not supersede the newer receipt, even if its editable date is later.
        jdbc.update("UPDATE device_usage SET status='IN_USE',end_time=NULL,start_time='2030-01-01' WHERE id=41");
        assertThat(tx.<Boolean>execute(status -> service.returnDevice(41L, "Old pending return"))).isTrue();
        assertLiveAssignment();
        jdbc.update("UPDATE device_usage SET status='IN_USE',end_time=NULL WHERE id=41");
        DeviceUsageRecord change = new DeviceUsageRecord(); change.setId(41L); change.setStatus("RETURNED");
        tx.executeWithoutResult(status -> service.updateDeviceUsageRecord(change));
        assertLiveAssignment();
        jdbc.update("UPDATE device_usage SET status='IN_USE',end_time=NULL WHERE id=41");
        tx.executeWithoutResult(status -> service.deleteDeviceUsageRecord(41L));
        assertLiveAssignment(); assertThat(service.getById(42L)).isNotNull();
        assertThat(tx.<Boolean>execute(status -> service.returnDevice(42L, "Actual return"))).isTrue();
        assertThat(jdbc.queryForObject("SELECT employee_id FROM device_management WHERE id=9", Long.class)).isNull();
        assertThat(jdbc.queryForObject("SELECT status FROM device_management WHERE id=9", String.class)).isEqualTo("IDLE");
        var completedAt = service.getById(42L).getEndTime();
        assertThat(tx.<Boolean>execute(status -> service.returnDevice(42L, "Repeated actual return"))).isTrue();
        assertThat(service.getById(42L).getEndTime()).isEqualTo(completedAt);
        jdbc.update("INSERT INTO device_usage(id,device_id,employee_id,status,start_time) VALUES(43,9,11,'IN_USE','2022-01-01')");
        jdbc.update("UPDATE device_management SET employee_id=11,status='IN_USE' WHERE id=9");
        tx.executeWithoutResult(status -> {
            var before = participant.related(actor, "DEVICE", "UNASSIGN_EMPLOYEE", "9", new Object[]{9L}, List.of(), true);
            assertThat(before).extracting(item -> item.resourceId()).containsExactly("43");
            assertThat(service.updateRecordOnUnassign(9L, "Current unassign")).isTrue();
            var after = participant.related(actor, "DEVICE", "UNASSIGN_EMPLOYEE", "9", new Object[]{9L}, before, false);
            assertThat(after).singleElement().satisfies(item -> {
                assertThat(item.resourceId()).isEqualTo("43"); assertThat(item.fields()).containsEntry("status", "RETURNED");
            });
        });
        assertThat(service.getById(43L).getEndTime()).isNotNull();
        assertThat(jdbc.queryForObject("SELECT employee_id FROM device_management WHERE id=9", Long.class)).isNull();
    }

    @Test void deviceUnassignClearsNullableColumnClosesAuditedReceiptAndIsIdempotent() {
        tx.executeWithoutResult(status -> {
            var before = participant.related(actor, "DEVICE", "removeEmployeeFromDevice", "9", new Object[]{9L}, List.of(), true);
            assertThat(before).extracting(item -> item.resourceId()).containsExactly("41");
            assertThat(devices.removeEmployeeFromDevice(9L)).isTrue();
            var after = participant.related(actor, "DEVICE", "removeEmployeeFromDevice", "9", new Object[]{9L}, before, false);
            assertThat(after).singleElement().satisfies(item -> {
                assertThat(item.fields()).containsEntry("status", "RETURNED");
                assertThat(item.fields().get("end_time")).isNotNull();
            });
            participant.advanceVersion(before.get(0), after.get(0));
        });
        assertThat(jdbc.queryForObject("SELECT employee_id FROM device_management WHERE id=9", Long.class)).isNull();
        assertThat(jdbc.queryForObject("SELECT status FROM device_management WHERE id=9", String.class)).isEqualTo("IDLE");
        assertThat(service.getById(41L).getVersion()).isEqualTo(1L);
        var receipt = jdbc.queryForMap("SELECT * FROM device_usage WHERE id=41");
        assertThat(tx.<Boolean>execute(status -> devices.removeEmployeeFromDevice(9L))).isTrue();
        assertThat(jdbc.queryForMap("SELECT * FROM device_usage WHERE id=41")).isEqualTo(receipt);
    }

    @Test void explicitDeviceUnassignDoesNotRewriteAnOlderOpenReceipt() {
        jdbc.update("INSERT INTO device_usage(id,device_id,employee_id,status,start_time,end_time) VALUES(42,9,11,'RETURNED','2021-01-01','2021-01-02')");
        var before = jdbc.queryForList("SELECT * FROM device_usage ORDER BY id");
        assertThat(tx.<Boolean>execute(status -> devices.removeEmployeeFromDevice(9L))).isTrue();
        assertThat(jdbc.queryForObject("SELECT employee_id FROM device_management WHERE id=9", Long.class)).isNull();
        assertThat(jdbc.queryForList("SELECT * FROM device_usage ORDER BY id")).isEqualTo(before);
    }

    @ParameterizedTest
    @CsvSource({"DETECTION,DETECTION,IN_USE", "IMAGE_CAPTURE,COLLECTION,IN_USE",
            "DETECTION,MAINTENANCE,MAINTENANCE", "IMAGE_CAPTURE,MAINTENANCE,MAINTENANCE"})
    void assignmentAndReceiptKeepTheIntendedDeviceState(String deviceType, String employeeType, String expectedStatus) {
        jdbc.update("UPDATE employee SET employee_type=?,status='ACTIVE' WHERE id=11", employeeType);
        jdbc.update("UPDATE device_management SET employee_id=NULL,status='IDLE',device_type=? WHERE id=9", deviceType);
        assertThat(tx.<Boolean>execute(status -> employees.assignDeviceToEmployee(11L, 9L))).isTrue();
        assertThat(jdbc.queryForObject("SELECT status FROM device_management WHERE id=9", String.class)).isEqualTo(expectedStatus);
        assertThat(jdbc.queryForObject("SELECT employee_id FROM device_management WHERE id=9", Long.class)).isEqualTo(11L);
        var newest = jdbc.queryForMap("SELECT * FROM device_usage ORDER BY id DESC LIMIT 1");
        assertThat(newest).containsEntry("status", "IN_USE").containsEntry("employee_name", "Current employee");
        assertThat(newest.get("end_time")).isNull();
    }

    @Test void receiptFailureRollsBackTheAlreadyWrittenAssignment() {
        jdbc.update("UPDATE employee SET employee_type='MAINTENANCE',status='ACTIVE' WHERE id=11");
        jdbc.update("UPDATE device_management SET employee_id=NULL,status='IDLE',device_type='DETECTION' WHERE id=9");
        var before = jdbc.queryForMap("SELECT * FROM device_management WHERE id=9");
        var failingHistory = mock(DeviceUsageRecordService.class);
        when(failingHistory.createRecordOnAssign(eq(9L), eq(11L), anyString())).thenAnswer(call -> {
            // The failure must follow the real device write, not a mapper binding error.
            assertThat(jdbc.queryForObject("SELECT employee_id FROM device_management WHERE id=9", Long.class)).isEqualTo(11L);
            assertThat(jdbc.queryForObject("SELECT status FROM device_management WHERE id=9", String.class)).isEqualTo("MAINTENANCE");
            assertThat(jdbc.queryForObject("SELECT version FROM device_management WHERE id=9", Integer.class)).isEqualTo(1);
            return false;
        });
        ReflectionTestUtils.setField(employees, "deviceUsageRecordService", failingHistory);
        assertThatThrownBy(() -> tx.executeWithoutResult(status -> employees.assignDeviceToEmployee(11L, 9L)))
                .isInstanceOf(BusinessException.class);
        verify(failingHistory).createRecordOnAssign(eq(9L), eq(11L), anyString());
        assertThat(jdbc.queryForMap("SELECT * FROM device_management WHERE id=9")).isEqualTo(before);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM device_usage", Integer.class)).isEqualTo(1);
    }

    @Test void failedDeviceReleaseRollsBackTheClosedReceipt() {
        var failingDevices = mock(DeviceMapper.class);
        Device assigned = devices.getDeviceById(9L);
        assertAssignedDeviceRead(assigned);
        when(failingDevices.selectForUsageUpdate(9L)).thenReturn(assigned);
        when(failingDevices.updateEmployeeId(9L, null)).thenAnswer(call -> {
            assertThat(service.getById(41L).getStatus()).isEqualTo("RETURNED");
            assertThat(service.getById(41L).getEndTime()).isNotNull();
            return 0;
        });
        ReflectionTestUtils.setField(service, "deviceMapper", failingDevices);
        var before = jdbc.queryForMap("SELECT * FROM device_usage WHERE id=41");
        assertThatThrownBy(() -> tx.executeWithoutResult(status -> devices.removeEmployeeFromDevice(9L)))
                .isInstanceOf(BusinessException.class);
        verify(failingDevices).updateEmployeeId(9L, null);
        assertThat(jdbc.queryForMap("SELECT * FROM device_usage WHERE id=41")).isEqualTo(before);
        assertLiveAssignment();
    }

    private void assertLiveAssignment() {
        assertThat(jdbc.queryForObject("SELECT employee_id FROM device_management WHERE id=9", Long.class)).isEqualTo(11L);
        assertThat(jdbc.queryForObject("SELECT status FROM device_management WHERE id=9", String.class)).isEqualTo("IN_USE");
    }

    private void assertAssignedDeviceRead(Device device) {
        assertThat(device.getId()).isEqualTo(9L);
        assertThat(device.getEmployeeId()).isEqualTo(11L);
        assertThat(device.getEmployee()).isNotNull();
        assertThat(device.getEmployee().getId()).isEqualTo(11L);
        assertThat(device.getEmployee().getName()).isEqualTo("Current employee");
    }

    private void assertBlockedConcurrentWrite(String sql) {
        var executor = Executors.newSingleThreadExecutor();
        try {
            var result = executor.submit(() -> {
                try (var connection = jdbc.getDataSource().getConnection(); var statement = connection.createStatement()) {
                    statement.execute("SET SESSION innodb_lock_wait_timeout=1");
                    try { statement.executeUpdate(sql); return 0; }
                    catch (SQLException blocked) { return blocked.getErrorCode(); }
                }
            });
            assertThat(result.get(8, TimeUnit.SECONDS)).as("competing writer must wait on the live reference lock").isEqualTo(1205);
        } catch (Exception failure) { throw new AssertionError("Could not verify reference transaction lock", failure); }
        finally { executor.shutdownNow(); }
    }
}
