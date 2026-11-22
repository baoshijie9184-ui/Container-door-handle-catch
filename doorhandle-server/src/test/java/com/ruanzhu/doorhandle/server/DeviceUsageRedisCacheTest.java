package com.ruanzhu.doorhandle.server;

import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.ruanzhu.doorhandle.framework.config.RedisCacheConfig;
import com.ruanzhu.doorhandle.framework.config.properties.AppRedisProperties;
import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.entity.DeviceUsageRecord;
import com.ruanzhu.doorhandle.module.device.entity.Employee;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceCaptureAlertMapper;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceMapper;
import com.ruanzhu.doorhandle.module.device.mapper.DeviceUsageRecordMapper;
import com.ruanzhu.doorhandle.module.device.mapper.EmployeeMapper;
import com.ruanzhu.doorhandle.module.device.service.impl.DeviceServiceImpl;
import com.ruanzhu.doorhandle.module.device.service.impl.DeviceUsageRecordServiceImpl;
import com.ruanzhu.doorhandle.module.device.service.impl.EmployeeServiceImpl;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.beans.BeanUtils;
import org.springframework.cache.Cache;
import org.springframework.cache.annotation.AnnotationCacheOperationSource;
import org.springframework.cache.interceptor.CacheInterceptor;
import org.springframework.data.redis.cache.RedisCacheManager;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.http.converter.json.Jackson2ObjectMapperBuilder;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.support.TransactionTemplate;

import java.io.Serializable;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Real Redis and Spring cache/transaction interceptors; DAO effects are deterministic doubles.
 * Real MySQL assignment/receipt rollback is covered by DeviceUsageHistoryMySqlTest. */
@EnabledIfEnvironmentVariable(named = "DOORHANDLE_CACHE_REDIS_TEST_HOST", matches = "127\\.0\\.0\\.1")
class DeviceUsageRedisCacheTest {
    enum Write { CREATE_USAGE, UPDATE_USAGE, DELETE_USAGE, CREATE_HISTORY, UPDATE_HISTORY,
        DELETE_HISTORY, RETURN, ASSIGN, UNASSIGN }
    private static final List<String> DEVICE_KEYS = List.of("all", "unassigned", "detail:9", "stats", "capture-alerts:test");
    private LettuceConnectionFactory connection;
    private RedisCacheManager caches;
    private Cache unrelated;
    private TransactionTemplate tx;
    private DeviceUsageRecordServiceImpl usage;
    private DeviceServiceImpl devices;
    private EmployeeServiceImpl employees;
    private final DeviceMapper deviceRows = mock(DeviceMapper.class);
    private final EmployeeMapper employeeRows = mock(EmployeeMapper.class);
    private final DeviceUsageRecordMapper usageRows = mock(DeviceUsageRecordMapper.class);
    private final AtomicReference<Device> databaseDevice = new AtomicReference<>();

    @BeforeAll static void initializeUsageMetadata() {
        // ServiceImpl.removeById reads MP metadata before calling the mocked mapper.
        // This fork must not depend on another module's native MySQL fixture.
        var table = TableInfoHelper.initTableInfo(
                new MapperBuilderAssistant(new MybatisConfiguration(), "usage-redis-cache-test"),
                DeviceUsageRecord.class);
        assertThat(TableInfoHelper.getTableInfo(DeviceUsageRecord.class)).isSameAs(table);
        assertThat(table.getTableName()).isEqualTo("device_usage");
        assertThat(table.getKeyProperty()).isEqualTo("id");
        assertThat(table.isWithLogicDelete()).isFalse();
    }

    @BeforeEach void setup() {
        var standalone = new RedisStandaloneConfiguration("127.0.0.1",
                Integer.parseInt(System.getenv().getOrDefault("DOORHANDLE_CACHE_REDIS_TEST_PORT", "6379")));
        standalone.setDatabase(Integer.parseInt(System.getenv().getOrDefault("DOORHANDLE_CACHE_REDIS_TEST_DATABASE", "0")));
        String password = System.getenv("DOORHANDLE_CACHE_REDIS_TEST_PASSWORD");
        if (password != null && !password.isBlank()) standalone.setPassword(password);
        connection = new LettuceConnectionFactory(standalone); connection.afterPropertiesSet();
        String prefix = "doorhandlecatch:verify:usage:" + UUID.randomUUID();
        caches = manager(prefix);
        unrelated = manager(prefix + ":other").getCache("device");
        unrelated.put("detail:9", "unrelated namespace");
        caches.getCache("model").put("metadata:105", "unrelated cache");
        // Existing test-only H2 dependency supplies real Spring commit/rollback callbacks;
        // no application tables or production resources are used here.
        tx = new TransactionTemplate(new DataSourceTransactionManager(
                new DriverManagerDataSource("jdbc:h2:mem:usage-cache-" + UUID.randomUUID(), "sa", "")));

        Device device = new Device(); device.setId(9L); device.setDeviceCode("D9");
        device.setEmployeeId(11L); device.setStatus("IN_USE"); device.setVersion(2);
        databaseDevice.set(device);
        Employee employee = new Employee(); employee.setId(11L); employee.setName("Employee");
        employee.setEmployeeType("MAINTENANCE"); employee.setStatus("ACTIVE"); employee.setHireDate("2020年春");
        when(employeeRows.selectForUsageReference(11L)).thenReturn(employee);
        when(employeeRows.selectById(11L)).thenReturn(employee);
        when(deviceRows.selectById(9L)).thenAnswer(call -> deviceCopy());
        when(deviceRows.selectForUsageReference(9L)).thenAnswer(call -> deviceCopy());
        when(deviceRows.selectForUsageUpdate(9L)).thenAnswer(call -> deviceCopy());
        when(deviceRows.getDeviceWithEmployee(9L)).thenAnswer(call -> deviceCopy());
        when(deviceRows.selectList(any())).thenAnswer(call -> new ArrayList<>(List.of(deviceCopy())));
        when(deviceRows.selectList(isNull())).thenAnswer(call -> new ArrayList<>(List.of(deviceCopy())));
        when(deviceRows.updateById(any(Device.class))).thenAnswer(call -> {
            Device value = new Device(); BeanUtils.copyProperties(call.getArgument(0), value);
            databaseDevice.set(value); return 1;
        });
        when(deviceRows.updateEmployeeId(9L, null)).thenAnswer(call -> {
            Device value = deviceCopy(); value.setEmployeeId(null); value.setStatus("IDLE");
            databaseDevice.set(value); return 1;
        });
        when(usageRows.selectForReferenceUpdate(41L)).thenAnswer(call -> receipt());
        when(usageRows.selectNewestForDeviceUpdate(9L)).thenAnswer(call -> receipt());
        when(usageRows.insert(any(DeviceUsageRecord.class))).thenReturn(1);
        when(usageRows.updateById(any(DeviceUsageRecord.class))).thenReturn(1);
        when(usageRows.deleteById(any(Serializable.class))).thenReturn(1);

        var target = new DeviceUsageRecordServiceImpl();
        ReflectionTestUtils.setField(target, "baseMapper", usageRows);
        ReflectionTestUtils.setField(target, "deviceUsageRecordMapper", usageRows);
        ReflectionTestUtils.setField(target, "deviceMapper", deviceRows);
        ReflectionTestUtils.setField(target, "employeeMapper", employeeRows);
        usage = cached(target);
        devices = cached(new DeviceServiceImpl(deviceRows, mock(DeviceCaptureAlertMapper.class), usage, mock(BusinessUserDirectory.class)));
        var employeeTarget = new EmployeeServiceImpl();
        ReflectionTestUtils.setField(employeeTarget, "employeeMapper", employeeRows);
        ReflectionTestUtils.setField(employeeTarget, "deviceMapper", deviceRows);
        ReflectionTestUtils.setField(employeeTarget, "deviceUsageRecordService", usage);
        employees = cached(employeeTarget);
        warm();
    }

    @AfterEach void cleanup() {
        try {
            if (caches != null) {
                for (String key : DEVICE_KEYS) caches.getCache("device").evict(key);
                caches.getCache("dashboard").evict("stats");
                caches.getCache("model").evict("metadata:105");
            }
            if (unrelated != null) unrelated.evict("detail:9");
        } finally { if (connection != null) connection.destroy(); }
    }

    @ParameterizedTest @EnumSource(Write.class)
    void everyUsageWriteEvictsOnlyItsCachesAfterCommit(Write write) {
        tx.executeWithoutResult(status -> {
            write(write);
            assertWarm();
        });
        assertEvicted();
        assertThat(devices.getDeviceById(9L)).isEqualTo(databaseDevice.get());
        // A second request is an actual Redis cache hit, not another DAO call.
        clearInvocations(deviceRows);
        assertThat(devices.getDeviceById(9L)).isEqualTo(databaseDevice.get());
        verify(deviceRows, never()).getDeviceWithEmployee(9L);
    }

    @ParameterizedTest @EnumSource(Write.class)
    void rolledBackOuterTransactionKeepsWarmCaches(Write write) {
        tx.executeWithoutResult(status -> {
            write(write);
            assertWarm();
            status.setRollbackOnly();
        });
        assertWarm();
    }

    @Test void failedUsageWriteLeavesCachesIntact() {
        when(usageRows.insert(any(DeviceUsageRecord.class))).thenThrow(new IllegalStateException("fixture write rejected"));
        assertThatThrownBy(() -> tx.executeWithoutResult(status -> usage.createDeviceUsageRecord(receipt())))
                .isInstanceOf(IllegalStateException.class);
        assertWarm();
    }

    @Test void deviceSideUnassignInvalidatesNestedUsageAndDeviceCachesOnlyAfterCommit() {
        tx.executeWithoutResult(status -> {
            assertThat(devices.removeEmployeeFromDevice(9L)).isTrue();
            assertWarm();
        });
        assertEvicted();
        assertThat(devices.getDeviceById(9L).getEmployeeId()).isNull();
        assertThat(devices.getDeviceById(9L).getStatus()).isEqualTo("IDLE");
    }

    @Test void maintenanceAssignmentReadsBackMaintenanceAfterNestedCacheEviction() {
        databaseDevice.get().setEmployeeId(null); databaseDevice.get().setStatus("IDLE");
        tx.executeWithoutResult(status -> {
            assertThat(employees.assignDeviceToEmployee(11L, 9L)).isTrue();
            assertWarm();
        });
        assertEvicted();
        assertThat(devices.getDeviceById(9L).getStatus()).isEqualTo("MAINTENANCE");
        assertThat(devices.getDeviceById(9L).getEmployeeId()).isEqualTo(11L);
    }

    private void write(Write write) {
        var value = receipt();
        switch (write) {
            case CREATE_USAGE -> usage.createDeviceUsageRecord(value);
            case UPDATE_USAGE -> { value.setStatus("RETURNED"); usage.updateDeviceUsageRecord(value); }
            case DELETE_USAGE -> usage.deleteDeviceUsageRecord(41L);
            case CREATE_HISTORY -> assertThat(usage.createRecord(value)).isTrue();
            case UPDATE_HISTORY -> { value.setRemarks("Corrected note"); assertThat(usage.updateRecord(value)).isTrue(); }
            case DELETE_HISTORY -> assertThat(usage.deleteRecord(41L)).isTrue();
            case RETURN -> assertThat(usage.returnDevice(41L, "Returned")).isTrue();
            case ASSIGN -> assertThat(usage.createRecordOnAssign(9L, 11L, "Maintenance")).isTrue();
            case UNASSIGN -> assertThat(usage.updateRecordOnUnassign(9L, "Returned")).isTrue();
        }
    }

    private void warm() {
        devices.getAllDevices(); devices.getUnassignedDevices(); devices.getDeviceById(9L); devices.getDeviceStats();
        caches.getCache("device").put("capture-alerts:test", "owned alert page");
        caches.getCache("dashboard").put("stats", Map.of("total", 1));
        assertWarm();
    }

    private void assertWarm() {
        for (String key : DEVICE_KEYS) assertThat(caches.getCache("device").get(key)).as(key).isNotNull();
        assertThat(caches.getCache("dashboard").get("stats")).isNotNull();
        assertUnrelated();
    }

    private void assertEvicted() {
        for (String key : DEVICE_KEYS) assertThat(caches.getCache("device").get(key)).as(key).isNull();
        assertThat(caches.getCache("dashboard").get("stats")).isNull();
        assertUnrelated();
    }

    private void assertUnrelated() {
        assertThat(unrelated.get("detail:9", String.class)).isEqualTo("unrelated namespace");
        assertThat(caches.getCache("model").get("metadata:105", String.class)).isEqualTo("unrelated cache");
    }

    private Device deviceCopy() { Device copy = new Device(); BeanUtils.copyProperties(databaseDevice.get(), copy); return copy; }
    private static DeviceUsageRecord receipt() {
        var value = new DeviceUsageRecord(); value.setId(41L); value.setDeviceId(9L); value.setEmployeeId(11L);
        value.setStatus("IN_USE"); return value;
    }
    private RedisCacheManager manager(String prefix) {
        var properties = new AppRedisProperties(); properties.setKeyPrefix(prefix);
        var manager = new RedisCacheConfig(properties, Jackson2ObjectMapperBuilder.json().build()).redisCacheManager(connection);
        manager.afterPropertiesSet(); return manager;
    }
    @SuppressWarnings("unchecked") private <T> T cached(T target) {
        var interceptor = new CacheInterceptor(); interceptor.setCacheManager(caches);
        interceptor.setCacheOperationSources(new AnnotationCacheOperationSource());
        interceptor.afterPropertiesSet(); interceptor.afterSingletonsInstantiated();
        var proxy = new ProxyFactory(target); proxy.setProxyTargetClass(true); proxy.addAdvice(interceptor);
        return (T) proxy.getProxy();
    }
}
