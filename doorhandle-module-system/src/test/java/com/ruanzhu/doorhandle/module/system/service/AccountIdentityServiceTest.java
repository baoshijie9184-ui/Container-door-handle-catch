package com.ruanzhu.doorhandle.module.system.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.extension.spring.MybatisSqlSessionFactoryBean;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.organization.EmployeeDirectoryApi;
import com.ruanzhu.doorhandle.module.system.mapper.*;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.junit.jupiter.api.*;
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

/** 使用真实 Mapper、唯一约束和 Spring 事务验证身份关联；H2 不代替 MySQL 验收。 */
class AccountIdentityServiceTest {
    AnnotationConfigApplicationContext context;
    JdbcTemplate jdbc;
    AccountIdentityService service;
    final TenantPrincipal boss = principal(1, "boss", "SUPERVISOR");
    final TenantPrincipal alice = principal(2, "alice", "INSPECTOR");
    @BeforeEach void setup() {
        context = new AnnotationConfigApplicationContext(); context.register(Config.class); context.refresh();
        jdbc = context.getBean(JdbcTemplate.class); service = context.getBean(AccountIdentityService.class);
        jdbc.execute("CREATE TABLE users(id BIGINT PRIMARY KEY, username VARCHAR(50),password VARCHAR(255),email VARCHAR(100),phone VARCHAR(20),role VARCHAR(16),created_at TIMESTAMP,updated_at TIMESTAMP)");
        jdbc.execute("CREATE TABLE employee(id BIGINT PRIMARY KEY,employee_number VARCHAR(50),name VARCHAR(50),status VARCHAR(20),employee_type VARCHAR(50),department_id BIGINT,department VARCHAR(100))");
        jdbc.execute("CREATE TABLE account_employee_binding(user_id BIGINT PRIMARY KEY REFERENCES users(id),employee_id BIGINT UNIQUE REFERENCES employee(id),version INT NOT NULL)");
        jdbc.execute("CREATE TABLE organization_binding_audit(id BIGINT AUTO_INCREMENT PRIMARY KEY,user_id BIGINT,username VARCHAR(50),actor_user_id BIGINT,actor_username VARCHAR(50),before_employee_id BIGINT,after_employee_id BIGINT,binding_version INT,action VARCHAR(16),created_at TIMESTAMP)");
        jdbc.update("INSERT INTO users(id,username,password,role) VALUES(1,'boss','hidden','SUPERVISOR'),(2,'alice','hidden','INSPECTOR'),(3,'bob','hidden','INSPECTOR')");
        jdbc.update("INSERT INTO employee VALUES(10,'EMP10','Alice','ACTIVE','DETECTION',20,'检测部'),(11,'EMP11','Bob','ACTIVE','COLLECTION',20,'检测部'),(12,'EMP12','Former','RESIGNED','DETECTION',20,'检测部'),(13,'EMP13','Unknown','ACTIVE','DETECTION',NULL,'')");
    }
    @AfterEach void close() { context.close(); }
    @Test void bindingDoesNotChangeRoleOrScopeAndResponseOmitsCredentials() throws Exception {
        var result = service.bind(boss, 2L, 10L, 0);
        assertThat(result.employeeId()).isEqualTo(10L); assertThat(result.departmentId()).isEqualTo(20L);
        assertThat(result.role()).isEqualTo("INSPECTOR"); assertThat(result.dataScope()).isEqualTo("OWNED_OR_ASSIGNED");
        assertThat(service.mine(alice)).isEqualTo(result);
        assertThat(new ObjectMapper().writeValueAsString(result)).doesNotContain("hidden", "password", "phone", "token");
    }
    @Test void repeatedBindingDoesNotRepeatAuditAndUnbindingPreservesVersion() {
        service.bind(boss, 2L, 10L, 0);
        assertThat(service.bind(boss, 2L, 10L, 1).bindingVersion()).isEqualTo(1);
        assertThat(service.audit(boss, 2L)).hasSize(1);
        assertThat(service.bind(boss, 2L, null, 1).bindingVersion()).isEqualTo(2);
        assertThat(service.mine(alice).employeeId()).isNull();
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
        jdbc.execute("ALTER TABLE organization_binding_audit ADD CONSTRAINT fail_audit CHECK(action<>'BIND')");
        assertThatThrownBy(() -> service.bind(boss, 2L, 10L, 0)).isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThat(service.mine(alice).bindingVersion()).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM account_employee_binding", Long.class)).isZero();
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
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM organization_binding_audit", Long.class)).isEqualTo(1);
        } finally { workers.shutdownNow(); }
    }
    @Test void boundEmployeeCannotBeDeletedAndInvalidArgumentsDoNotWrite() {
        service.bind(boss, 2L, 10L, 0);
        assertThatThrownBy(() -> jdbc.update("DELETE FROM employee WHERE id=10")).isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThatThrownBy(() -> service.bind(boss, 2L, 11L, null)).hasMessageContaining("参数");
        assertThatThrownBy(() -> service.bind(boss, 2L, -1L, 1)).hasMessageContaining("参数");
        assertThat(service.audit(boss, 2L)).hasSize(1);
    }
    static TenantPrincipal principal(long id, String username, String role) {
        return new TenantPrincipal(id, username, "", List.of(new SimpleGrantedAuthority("ROLE_" + role)));
    }
    @Configuration @EnableTransactionManagement
    static class Config {
        @Bean DataSource source() { return new DriverManagerDataSource("jdbc:h2:mem:identity" + UUID.randomUUID() + ";MODE=MySQL;DB_CLOSE_DELAY=-1", "sa", ""); }
        @Bean JdbcTemplate jdbc(DataSource source) { return new JdbcTemplate(source); }
        @Bean DataSourceTransactionManager transactions(DataSource source) { return new DataSourceTransactionManager(source); }
        @Bean SqlSessionTemplate sql(DataSource source) throws Exception {
            var config = new MybatisConfiguration(); config.setMapUnderscoreToCamelCase(true);
            config.addMapper(UserMapper.class); config.addMapper(AccountEmployeeBindingMapper.class); config.addMapper(OrganizationBindingAuditMapper.class);
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
            return new AccountIdentityService(sql.getMapper(UserMapper.class), sql.getMapper(AccountEmployeeBindingMapper.class), sql.getMapper(OrganizationBindingAuditMapper.class), employees);
        }
    }
}
