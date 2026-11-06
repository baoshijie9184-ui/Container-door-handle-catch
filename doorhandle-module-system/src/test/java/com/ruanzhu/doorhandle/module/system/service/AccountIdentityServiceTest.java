package com.ruanzhu.doorhandle.module.system.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.extension.spring.MybatisSqlSessionFactoryBean;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.organization.EmployeeDirectoryApi;
import com.ruanzhu.doorhandle.module.system.mapper.*;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import com.ruanzhu.doorhandle.module.system.support.OperationsMySqlFixture;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import javax.sql.DataSource;
import java.util.*;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;

/** Actual compact DDL, mapper, FK, triggers and transaction behavior; ECS execution only. */
@EnabledIfSystemProperty(named="doorhandle.operations.mysql.config",matches=".+")
class AccountIdentityServiceTest {
    AnnotationConfigApplicationContext context;
    JdbcTemplate jdbc;
    AccountIdentityService service;
    OperationsMySqlFixture fixture;
    final TenantPrincipal boss = principal(1, "boss", "SUPERVISOR");
    final TenantPrincipal alice = principal(2, "alice", "INSPECTOR");
    @BeforeEach void setup() throws Exception {
        fixture=new OperationsMySqlFixture(false);
        context = new AnnotationConfigApplicationContext();
        context.registerBean(DataSource.class,()->fixture.dataSource());context.register(Config.class); context.refresh();
        jdbc = context.getBean(JdbcTemplate.class); service = context.getBean(AccountIdentityService.class);
        jdbc.update("INSERT INTO users(id,username,password,role) VALUES(1,'boss','hidden','SUPERVISOR'),(2,'alice','hidden','INSPECTOR'),(3,'bob','hidden','INSPECTOR')");
        jdbc.update("INSERT INTO organization_department(id,name) VALUES(20,'检测部')");
        jdbc.update("""
                INSERT INTO employee(id,employee_number,name,status,employee_type,department_id,department,contact,gender,hire_date) VALUES
                (10,'EMP10','Alice','ACTIVE','DETECTION',20,'检测部','fixture','UNKNOWN','2020-01-01'),
                (11,'EMP11','Bob','ACTIVE','COLLECTION',20,'检测部','fixture','UNKNOWN','2020-01-01'),
                (12,'EMP12','Former','RESIGNED','DETECTION',20,'检测部','fixture','UNKNOWN','2020-01-01'),
                (13,'EMP13','Unknown','ACTIVE','DETECTION',NULL,'','fixture','UNKNOWN','2020-01-01')
                """);
    }
    @AfterEach void close() throws Exception { try {if(context!=null)context.close();}finally{if(fixture!=null)fixture.close();} }
    @Test void bindingDoesNotChangeRoleOrScopeAndResponseOmitsCredentials() throws Exception {
        jdbc.update("UPDATE users SET email='alice@example.test',phone='123',updated_at=TIMESTAMP '2026-01-01 12:00:00' WHERE id=2");
        var before = jdbc.queryForMap("SELECT username,password,email,phone,role,updated_at FROM users WHERE id=2");
        var result = service.bind(boss, 2L, 10L, 0);
        assertThat(result.employeeId()).isEqualTo(10L); assertThat(result.departmentId()).isEqualTo(20L);
        assertThat(result.role()).isEqualTo("INSPECTOR"); assertThat(result.dataScope()).isEqualTo("OWNED_OR_ASSIGNED");
        assertThat(service.mine(alice)).isEqualTo(result);
        assertThat(new ObjectMapper().writeValueAsString(result)).doesNotContain("hidden", "password", "phone", "token");
        assertThat(jdbc.queryForMap("SELECT username,password,email,phone,role,updated_at FROM users WHERE id=2")).isEqualTo(before);
    }
    @Test void neverBoundAccountsHaveVersionZeroWithoutAssociationRows() {
        assertThat(service.mine(alice).employeeId()).isNull();
        assertThat(service.mine(alice).bindingVersion()).isZero();
        assertThat(service.bind(boss, 2L, null, 0).bindingVersion()).isZero();
        assertThat(service.audit(boss, 2L)).isEmpty();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM users", Long.class)).isEqualTo(3);
        assertThat(jdbc.queryForObject("SELECT binding_history_present FROM users WHERE id=2", Boolean.class)).isFalse();
    }
    @Test void repeatedBindingDoesNotRepeatAuditAndUnbindingPreservesVersion() {
        service.bind(boss, 2L, 10L, 0);
        assertThat(service.bind(boss, 2L, 10L, 1).bindingVersion()).isEqualTo(1);
        assertThat(service.audit(boss, 2L)).hasSize(1);
        assertThat(service.bind(boss, 2L, null, 1).bindingVersion()).isEqualTo(2);
        assertThat(service.mine(alice).employeeId()).isNull();
        assertThat(jdbc.queryForObject("SELECT binding_history_present FROM users WHERE id=2", Boolean.class)).isTrue();
        assertThat(service.bind(boss, 2L, 11L, 2).bindingVersion()).isEqualTo(3);
        assertThat(service.audit(boss, 2L)).extracting(a -> a.getAction()).containsExactly("BIND", "UNBIND", "BIND");
    }
    @Test void oldVersionAndDuplicateEmployeeAreRejectedWithoutAudit() {
        service.bind(boss, 2L, 10L, 0);
        assertThatThrownBy(() -> service.bind(boss, 2L, 11L, 0)).hasMessageContaining("刷新");
        assertThatThrownBy(() -> service.bind(boss, 3L, 10L, 0)).hasMessageContaining("其他账号");
        assertThat(service.audit(boss, 3L)).isEmpty();
        assertThat(service.mine(alice).employeeId()).isEqualTo(10L);
    }
    @Test void employeeAndRevokedSupervisorCannotManageOthers() {
        assertThatThrownBy(() -> service.bind(alice, 3L, 10L, 0)).isInstanceOf(AccessDeniedException.class);
        assertThatThrownBy(() -> service.audit(alice, 3L)).isInstanceOf(AccessDeniedException.class);
        jdbc.update("UPDATE users SET role='INSPECTOR' WHERE id=1");
        assertThatThrownBy(() -> service.bind(boss, 2L, 10L, 0)).isInstanceOf(AccessDeniedException.class);
        assertThatThrownBy(() -> service.mine(principal(2, "bob", "INSPECTOR"))).isInstanceOf(AccessDeniedException.class);
    }
    @Test void missingInactiveAndUnorganizedEmployeesCannotBeBound() {
        assertThatThrownBy(() -> service.bind(boss, 2L, 99L, 0)).hasMessageContaining("员工不存在");
        assertThatThrownBy(() -> service.bind(boss, 2L, 12L, 0)).hasMessageContaining("在岗");
        assertThatThrownBy(() -> service.bind(boss, 2L, 13L, 0)).hasMessageContaining("部门");
        assertThat(service.audit(boss, 2L)).isEmpty();
    }
    @Test void failedAuditRollsBackBinding() {
        jdbc.execute("ALTER TABLE audit_event ADD CONSTRAINT fail_audit CHECK(action<>'BIND')");
        assertThatThrownBy(() -> service.bind(boss, 2L, 10L, 0)).isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThat(service.mine(alice).bindingVersion()).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM users WHERE employee_id IS NOT NULL OR binding_version<>0 OR binding_history_present=TRUE", Long.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM users", Long.class)).isEqualTo(3);
    }
    @Test void compareAndSetRejectsStaleVersionWithoutChangingAccount() {
        service.bind(boss, 2L, 10L, 0);
        var mapper = context.getBean(SqlSessionTemplate.class).getMapper(AccountEmployeeBindingMapper.class);
        assertThat(mapper.compareAndSet(2L, 11L, 0)).isZero();
        assertThat(service.mine(alice).employeeId()).isEqualTo(10L);
        assertThat(service.mine(alice).bindingVersion()).isEqualTo(1);
        assertThat(service.audit(boss, 2L)).hasSize(1);
    }
    @Test void explicitHistoricalEmptyBindingKeepsItsDeletionProtectionMarker() {
        jdbc.update("UPDATE users SET binding_history_present=TRUE WHERE id=2");
        assertThat(service.bind(boss, 2L, null, 0).bindingVersion()).isZero();
        assertThat(service.audit(boss, 2L)).isEmpty();
        assertThat(jdbc.queryForObject("SELECT binding_history_present FROM users WHERE id=2", Boolean.class)).isTrue();
    }
    @Test void failedUnbindAuditRollsBackTheExistingEmployeeAndVersion() {
        service.bind(boss, 2L, 10L, 0);
        jdbc.execute("ALTER TABLE audit_event ADD CONSTRAINT fail_unbind_audit CHECK(action<>'UNBIND')");
        assertThatThrownBy(() -> service.bind(boss, 2L, null, 1)).isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThat(service.mine(alice).employeeId()).isEqualTo(10L);
        assertThat(service.mine(alice).bindingVersion()).isEqualTo(1);
        assertThat(service.audit(boss, 2L)).hasSize(1);
    }
    @Test void concurrentAccountsCannotClaimTheSameEmployee() throws Exception {
        var workers = Executors.newFixedThreadPool(2); var start = new CountDownLatch(1);
        try {
            List<Future<Boolean>> futures = new ArrayList<>();
            for (long id : List.of(2L, 3L)) futures.add(workers.submit(() -> {
                start.await(); try { service.bind(boss, id, 10L, 0); return true; } catch (RuntimeException conflict) { return false; }
            }));
            start.countDown(); int succeeded = 0;
            for (var result : futures) if (result.get(10, TimeUnit.SECONDS)) succeeded++;
            assertThat(succeeded).isEqualTo(1);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='ORGANIZATION_BINDING'", Long.class)).isEqualTo(1);
        } finally { workers.shutdownNow(); }
    }
    @Test void boundEmployeeCannotBeDeletedAndInvalidArgumentsDoNotWrite() {
        service.bind(boss, 2L, 10L, 0);
        assertThatThrownBy(() -> jdbc.update("DELETE FROM employee WHERE id=10")).isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThatThrownBy(() -> service.bind(boss, 2L, 11L, null)).hasMessageContaining("参数");
        assertThatThrownBy(() -> service.bind(boss, 2L, -1L, 1)).hasMessageContaining("参数");
        assertThat(service.audit(boss, 2L)).hasSize(1);
    }
    @Test void auditKeepsOriginalNamesAndBeforeAfterEvidenceWhenProfilesChange() {
        service.bind(boss,2L,10L,0);service.bind(boss,2L,11L,1);
        jdbc.update("UPDATE users SET username='alice-renamed' WHERE id=2");
        var history=service.audit(boss,2L);
        assertThat(history).hasSize(2);
        assertThat(history.get(0).getAction()).isEqualTo("REBIND");
        assertThat(history.get(0).getBeforeEmployeeId()).isEqualTo(10L);
        assertThat(history.get(0).getAfterEmployeeId()).isEqualTo(11L);
        assertThat(history.get(0).getUsername()).isEqualTo("alice");
        assertThat(history.get(0).getActorUsername()).isEqualTo("boss");
        assertThat(history.get(0).getBindingVersion()).isEqualTo(2);
    }
    @Test void unboundEmployeeDeletionDoesNotEraseHistoricalAudit() {
        service.bind(boss,2L,10L,0);service.bind(boss,2L,null,1);
        jdbc.update("DELETE FROM employee WHERE id=10");
        assertThat(service.audit(boss,2L)).hasSize(2);
        assertThat(service.audit(boss,2L).get(0).getBeforeEmployeeId()).isEqualTo(10L);
        assertThat(service.audit(boss,2L).get(1).getAfterEmployeeId()).isEqualTo(10L);
    }
    @Test void supervisorIsRecheckedFromTheLockedRowBeforeMutation() throws Exception {
        var locked=new CountDownLatch(1);var revoke=new CountDownLatch(1);var checked=new CountDownLatch(1);var pool=Executors.newFixedThreadPool(2);
        var tx=new org.springframework.transaction.support.TransactionTemplate(context.getBean(DataSourceTransactionManager.class));
        tx.setIsolationLevel(org.springframework.transaction.TransactionDefinition.ISOLATION_READ_COMMITTED);
        var sql=context.getBean(SqlSessionTemplate.class);var actualUsers=sql.getMapper(UserMapper.class);
        var gatedUsers=org.mockito.Mockito.mock(UserMapper.class,org.mockito.AdditionalAnswers.delegatesTo(actualUsers));
        org.mockito.Mockito.doAnswer(invocation->{var identity=actualUsers.selectById(1L);checked.countDown();return identity;})
                .when(gatedUsers).selectById(1L);
        var gated=new AccountIdentityService(gatedUsers,sql.getMapper(AccountEmployeeBindingMapper.class),
                new OrganizationBindingAuditStore(jdbc),org.mockito.Mockito.mock(EmployeeDirectoryApi.class));
        try {
            var change=pool.submit(()->tx.executeWithoutResult(status->{
                jdbc.queryForObject("SELECT id FROM users WHERE id=1 FOR UPDATE",Long.class);locked.countDown();
                try {if(!revoke.await(10,TimeUnit.SECONDS))throw new IllegalStateException("revoke timeout");}
                catch(InterruptedException error){Thread.currentThread().interrupt();throw new IllegalStateException(error);}
                jdbc.update("UPDATE users SET role='INSPECTOR' WHERE id=1");
            }));
            assertThat(locked.await(10,TimeUnit.SECONDS)).isTrue();
            var mutation=pool.submit(()->tx.execute(status->gated.bind(boss,2L,10L,0)));
            assertThat(checked.await(10,TimeUnit.SECONDS)).isTrue();
            revoke.countDown();change.get(10,TimeUnit.SECONDS);
            assertThatThrownBy(()->mutation.get(10,TimeUnit.SECONDS)).hasCauseInstanceOf(AccessDeniedException.class);
        } finally {revoke.countDown();pool.shutdownNow();}
        assertThat(jdbc.queryForObject("SELECT binding_version FROM users WHERE id=2",Integer.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='ORGANIZATION_BINDING'",Long.class)).isZero();
    }
    static TenantPrincipal principal(long id, String username, String role) {
        return new TenantPrincipal(id, username, "", List.of(new SimpleGrantedAuthority("ROLE_" + role)));
    }
    @Configuration @EnableTransactionManagement
    static class Config {
        @Bean JdbcTemplate jdbc(DataSource source) { return new JdbcTemplate(source); }
        @Bean DataSourceTransactionManager transactions(DataSource source) { return new DataSourceTransactionManager(source); }
        @Bean SqlSessionTemplate sql(DataSource source) throws Exception {
            var config = new MybatisConfiguration(); config.setMapUnderscoreToCamelCase(true);
            config.addMapper(UserMapper.class); config.addMapper(AccountEmployeeBindingMapper.class);
            var factory = new MybatisSqlSessionFactoryBean(); factory.setDataSource(source); factory.setConfiguration(config);
            return new SqlSessionTemplate(factory.getObject());
        }
        @Bean AccountIdentityService service(SqlSessionTemplate sql, JdbcTemplate jdbc) {
            var employees = new EmployeeDirectoryApi() {
                public List<EmployeeIdentity> findAll(Collection<Long> ids) {
                    var result = new ArrayList<EmployeeIdentity>(); for (Long id : ids) result.addAll(read(id, false)); return result;
                }
                public EmployeeIdentity lock(Long id) {
                    assertThat(TransactionSynchronizationManager.isActualTransactionActive()).isTrue();
                    var rows = read(id, true); if (rows.isEmpty()) throw new IllegalArgumentException("员工不存在"); return rows.get(0);
                }
                private List<EmployeeIdentity> read(Long id, boolean lock) {
                    return jdbc.query("SELECT * FROM employee WHERE id=?" + (lock ? " FOR UPDATE" : ""),
                            (r, n) -> new EmployeeIdentity(r.getLong("id"), r.getString("employee_number"), r.getString("name"), r.getString("status"), r.getString("employee_type"), r.getObject("department_id", Long.class), r.getString("department")), id);
                }
            };
            return new AccountIdentityService(sql.getMapper(UserMapper.class), sql.getMapper(AccountEmployeeBindingMapper.class), new OrganizationBindingAuditStore(jdbc), employees);
        }
    }
}
