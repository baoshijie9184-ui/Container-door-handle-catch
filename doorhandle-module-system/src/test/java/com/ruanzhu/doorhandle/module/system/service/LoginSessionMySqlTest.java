package com.ruanzhu.doorhandle.module.system.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.extension.spring.MybatisSqlSessionFactoryBean;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.organization.EmployeeDirectoryApi;
import com.ruanzhu.doorhandle.contracts.security.*;
import com.ruanzhu.doorhandle.module.system.dto.LoginResponse;
import com.ruanzhu.doorhandle.module.system.mapper.*;
import com.ruanzhu.doorhandle.module.system.security.*;
import com.ruanzhu.doorhandle.module.system.support.OperationsMySqlFixture;
import com.ruanzhu.doorhandle.module.system.util.JwtUtil;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.support.TransactionTemplate;
import java.util.*;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;

/** Real MySQL, full 29-table DDL, current account facts, durable session races. ECS only. */
@EnabledIfSystemProperty(named="doorhandle.operations.mysql.config",matches=".+")
class LoginSessionMySqlTest {
    OperationsMySqlFixture fixture;JdbcTemplate jdbc;JwtUtil jwt;LoginSessionService sessions;LoginEligibilityService eligibility;AccountAccessService accounts;
    TransactionTemplate tx;final List<Object> events=new CopyOnWriteArrayList<>();
    @BeforeEach void setup()throws Exception{
        fixture=new OperationsMySqlFixture(false);jdbc=fixture.target();var manager=new DataSourceTransactionManager(fixture.dataSource());tx=new TransactionTemplate(manager);
        var configuration=new MybatisConfiguration();configuration.setMapUnderscoreToCamelCase(true);configuration.addMapper(UserMapper.class);configuration.addMapper(AccountEmployeeBindingMapper.class);
        var factory=new MybatisSqlSessionFactoryBean();factory.setDataSource(fixture.dataSource());factory.setConfiguration(configuration);var sql=new SqlSessionTemplate(factory.getObject());
        var properties=new LoginSessionProperties();properties.setEnabled(true);
        EmployeeDirectoryApi staff=new EmployeeDirectoryApi(){
            public List<EmployeeIdentity> findAll(Collection<Long> ids){var result=new ArrayList<EmployeeIdentity>();for(long id:ids)result.addAll(jdbc.query("SELECT id,employee_number,name,status,employee_type,department_id,department FROM employee WHERE id=?",(r,n)->new EmployeeIdentity(r.getLong(1),r.getString(2),r.getString(3),r.getString(4),r.getString(5),r.getObject(6,Long.class),r.getString(7)),id));return result;}
            public EmployeeIdentity lock(Long id){return jdbc.query("SELECT id,employee_number,name,status,employee_type,department_id,department FROM employee WHERE id=? FOR UPDATE",(r,n)->new EmployeeIdentity(r.getLong(1),r.getString(2),r.getString(3),r.getString(4),r.getString(5),r.getObject(6,Long.class),r.getString(7)),id).stream().findFirst().orElseThrow();}
        };
        eligibility=new LoginEligibilityService(sql.getMapper(UserMapper.class),sql.getMapper(AccountEmployeeBindingMapper.class),staff,properties);
        jwt=new JwtUtil();ReflectionTestUtils.setField(jwt,"secret","01234567890123456789012345678901");ReflectionTestUtils.setField(jwt,"expiration",3600L);ReflectionTestUtils.setField(jwt,"refreshExpiration",86400L);
        sessions=new LoginSessionService(jdbc,manager,eligibility,properties,jwt,new ObjectMapper(),events::add);sessions.validateSchema();
        accounts=new AccountAccessService(sql.getMapper(UserMapper.class),jdbc,eligibility,sessions);ReflectionTestUtils.setField(accounts,"mutations",true);
        jdbc.update("INSERT INTO users(id,username,password,role) VALUES(1,'boss-a','test-hash','SUPERVISOR'),(2,'boss-b','test-hash','SUPERVISOR'),(3,'inspector','test-hash','INSPECTOR')");
        jdbc.update("INSERT INTO organization_department(id,name) VALUES(20,'Detection')");
        jdbc.update("INSERT INTO employee(id,employee_number,name,status,employee_type,department_id,department,contact,gender,hire_date) VALUES(10,'E10','Inspector','ACTIVE','DETECTION',20,'Detection','fixture','UNKNOWN','2020-01-01')");
        jdbc.update("UPDATE users SET employee_id=10,binding_history_present=TRUE,binding_version=1 WHERE id=3");
    }
    @AfterEach void cleanup()throws Exception{if(fixture!=null)fixture.close();}
    String digest(LoginResponse response){return LoginSessionService.digest(jwt.getSessionId(response.getToken()));}
    LoginSessionAccess.Session active(LoginResponse response){return sessions.requireActive(response.getUserId(),response.getUsername(),digest(response));}
    TenantPrincipal boss(){return new TenantPrincipal(1L,"boss-a","",List.of(new SimpleGrantedAuthority("ROLE_SUPERVISOR")));}
    @Test void independentDevicesAndUsersHaveDistinctDurableSessionsAndLogoutIsScoped(){
        var a=sessions.login(1,"boss-a");var device=sessions.login(1,"boss-a");var other=sessions.login(2,"boss-b");var inspector=sessions.login(3,"inspector");
        assertThat(digest(a).equals(digest(device))).isFalse();assertThat(a.getAccountContext().equals(device.getAccountContext())).isFalse();
        sessions.logout(a.getToken(),null,a.getAccountContext());assertThatThrownBy(()->active(a)).isInstanceOf(org.springframework.security.core.AuthenticationException.class);
        assertThat(active(device).userId()).isEqualTo(1);assertThat(active(other).userId()).isEqualTo(2);assertThat(active(inspector).role()).isEqualTo("INSPECTOR");
        assertThat(events).filteredOn(LoginSessionRevoked.class::isInstance).hasSize(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE'",Integer.class)).isEqualTo(29);
    }
    @Test void sessionPersistsAcrossServiceInstancesAndNoBearerCredentialIsStored(){
        var issued=sessions.login(1,"boss-a");String raw=jdbc.queryForObject("SELECT payload_json FROM runtime_state WHERE namespace='LOGIN_SESSION'",String.class);
        assertThat(raw.contains(issued.getToken())||raw.contains(issued.getRefreshToken())||raw.contains(jwt.getSessionId(issued.getToken()))).isFalse();
        assertThat(raw).contains("refreshDigest");assertThat(jdbc.queryForObject("SELECT session_id IS NULL AND state_key IS NULL FROM runtime_state WHERE namespace='LOGIN_SESSION'",Boolean.class)).isTrue();
        var second=new LoginSessionService(jdbc,new DataSourceTransactionManager(fixture.dataSource()),eligibility,newEnabled(),jwt,new ObjectMapper(),events::add);
        assertThat(second.requireActive(1,"boss-a",digest(issued)).sessionDigest()).isEqualTo(digest(issued));
    }
    LoginSessionProperties newEnabled(){var value=new LoginSessionProperties();value.setEnabled(true);return value;}
    @Test void concurrentRefreshKeepsTheSameCredentialAndSerializesEveryRevision()throws Exception{
        var issued=sessions.login(1,"boss-a");var pool=Executors.newFixedThreadPool(4);var start=new CountDownLatch(1);
        try{var futures=new ArrayList<Future<LoginResponse>>();for(int i=0;i<4;i++)futures.add(pool.submit(()->{if(!start.await(5,TimeUnit.SECONDS))throw new IllegalStateException("start timeout");return sessions.refresh(issued.getRefreshToken(),issued.getAccountContext());}));start.countDown();
            for(var future:futures){var result=future.get(15,TimeUnit.SECONDS);assertThat(result.getRefreshToken().equals(issued.getRefreshToken())).isTrue();assertThat(active(result).sessionDigest()).isEqualTo(digest(issued));}
        }finally{start.countDown();pool.shutdownNow();}
        assertThat(jdbc.queryForObject("SELECT revision FROM runtime_state WHERE namespace='LOGIN_SESSION'",Long.class)).isEqualTo(4);
    }
    @Test void refreshLogoutRaceNeverResurrectsTheSession()throws Exception{
        var issued=sessions.login(1,"boss-a");var pool=Executors.newFixedThreadPool(2);var start=new CountDownLatch(1);
        try{var refresh=pool.submit(()->{try{start.await(5,TimeUnit.SECONDS);return sessions.refresh(issued.getRefreshToken(),issued.getAccountContext());}catch(org.springframework.security.core.AuthenticationException revoked){return null;}});
            var logout=pool.submit(()->{try{start.await(5,TimeUnit.SECONDS);sessions.logout(null,issued.getRefreshToken(),issued.getAccountContext());}catch(InterruptedException e){Thread.currentThread().interrupt();throw new IllegalStateException(e);}});
            start.countDown();logout.get(15,TimeUnit.SECONDS);var result=refresh.get(15,TimeUnit.SECONDS);if(result!=null)assertThatThrownBy(()->active(result)).isInstanceOf(org.springframework.security.core.AuthenticationException.class);
        }finally{start.countDown();pool.shutdownNow();}
        assertThatThrownBy(()->sessions.refresh(issued.getRefreshToken(),issued.getAccountContext())).isInstanceOf(org.springframework.security.core.AuthenticationException.class);
    }
    @Test void disabledAccountsAndPersonnelRevocationRecheckCurrentFacts(){
        var boss=sessions.login(2,"boss-b");jdbc.update("UPDATE users SET enabled=FALSE WHERE id=2");assertThatThrownBy(()->active(boss)).isInstanceOf(org.springframework.security.core.AuthenticationException.class);
        var person=sessions.login(3,"inspector");jdbc.update("UPDATE employee SET employee_type='COLLECTION' WHERE id=10");assertThatThrownBy(()->active(person)).isInstanceOf(org.springframework.security.core.AuthenticationException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM runtime_state WHERE namespace='LOGIN_SESSION' AND state_code='ACTIVE'",Integer.class)).isZero();
        assertThat(events).filteredOn(AccountAccessChanged.class::isInstance).hasSize(2);
    }
    @Test void roleChangeAndUnknownSessionDoNotReuseCachedAuthorities(){
        var issued=sessions.login(1,"boss-a");jdbc.update("UPDATE users SET role='INSPECTOR' WHERE id=1");assertThatThrownBy(()->active(issued)).isInstanceOf(org.springframework.security.core.AuthenticationException.class);
        assertThatThrownBy(()->sessions.requireActive(2,"boss-b","a".repeat(64))).isInstanceOf(org.springframework.security.core.AuthenticationException.class);
    }
    @Test void oldAccountContextCannotRefreshLogoutOrModifyAnotherSession(){
        var a=sessions.login(1,"boss-a");var b=sessions.login(2,"boss-b");
        assertThatThrownBy(()->sessions.refresh(b.getRefreshToken(),a.getAccountContext())).isInstanceOf(AccountContextChangedException.class);
        assertThatThrownBy(()->sessions.logout(b.getToken(),null,a.getAccountContext())).isInstanceOf(AccountContextChangedException.class);
        assertThat(active(a).userId()).isEqualTo(1);assertThat(active(b).userId()).isEqualTo(2);
    }
    @Test void expiryRevokesOnlyExpiredRowsAndPreservesMetadata(){
        var expired=sessions.login(1,"boss-a");var live=sessions.login(2,"boss-b");
        jdbc.update("UPDATE runtime_state SET window_started_at=UTC_TIMESTAMP(6)-INTERVAL 2 DAY,created_at=UTC_TIMESTAMP(6)-INTERVAL 2 DAY,window_ends_at=UTC_TIMESTAMP(6)-INTERVAL 1 DAY WHERE namespace='LOGIN_SESSION' AND owner_id=1");
        sessions.expireSessions();assertThatThrownBy(()->active(expired)).isInstanceOf(org.springframework.security.core.AuthenticationException.class);assertThat(active(live).userId()).isEqualTo(2);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM runtime_state WHERE namespace='LOGIN_SESSION'",Integer.class)).isEqualTo(2);
    }
    @Test void closedSchemaRejectsExtraCredentialFieldsWrongTypesAndSdkSlotUse(){
        sessions.login(1,"boss-a");
        for(String mutation:List.of("payload_json=JSON_SET(payload_json,'$.rawToken','forbidden')","payload_json=JSON_SET(payload_json,'$.userId','1')","session_id='not-sdk'","scope_key='raw-sid'","state_code='UNKNOWN'","window_ends_at=window_started_at"))
            assertThatThrownBy(()->jdbc.update("UPDATE runtime_state SET "+mutation+" WHERE namespace='LOGIN_SESSION'")).isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
    }
    @Test void accountCommandChecksVersionAndSelfProtectionAndRevokesOtherDevices(){
        var one=sessions.login(2,"boss-b");var two=sessions.login(2,"boss-b");
        var changed=tx.execute(status->accounts.change(boss(),2,new AccountAccessService.Change(false,"SUPERVISOR",0L,"disable-boss-b")));
        assertThat(changed.enabled()).isFalse();assertThat(changed.accountVersion()).isEqualTo(1);
        assertThatThrownBy(()->active(one)).isInstanceOf(org.springframework.security.core.AuthenticationException.class);assertThatThrownBy(()->active(two)).isInstanceOf(org.springframework.security.core.AuthenticationException.class);
        assertThatThrownBy(()->tx.execute(status->accounts.change(boss(),2,new AccountAccessService.Change(true,"SUPERVISOR",0L,"stale-version")))).isInstanceOf(com.ruanzhu.doorhandle.common.BusinessException.class);
        assertThatThrownBy(()->tx.execute(status->accounts.change(boss(),1,new AccountAccessService.Change(false,"INSPECTOR",0L,"self-disable")))).isInstanceOf(com.ruanzhu.doorhandle.common.BusinessException.class);
    }
    @Test void eligibilityEventsRevokeBeforeCommitAndRollbackKeepsThePreviousSession(){
        var issued=sessions.login(3,"inspector");
        try(var context=new org.springframework.context.annotation.AnnotationConfigApplicationContext()){
            context.registerBean(org.springframework.transaction.event.TransactionalEventListenerFactory.class,org.springframework.transaction.event.TransactionalEventListenerFactory::new);
            context.registerBean(LoginSessionService.class,()->sessions);context.refresh();
            assertThatThrownBy(()->tx.executeWithoutResult(status->{
                context.publishEvent(new EmployeeLoginEligibilityChanged(10));throw new IllegalStateException("rollback");
            })).isInstanceOf(IllegalStateException.class);
            assertThat(active(issued).userId()).isEqualTo(3);
            tx.executeWithoutResult(status->{
                context.publishEvent(new EmployeeLoginEligibilityChanged(10));
                assertThat(jdbc.queryForObject("SELECT state_code FROM runtime_state WHERE namespace='LOGIN_SESSION' AND owner_id=3",String.class)).isEqualTo("ACTIVE");
            });
            assertThatThrownBy(()->active(issued)).isInstanceOf(org.springframework.security.core.AuthenticationException.class);
        }
    }
    @Test void mutuallyDisablingSupervisorsCannotBothSucceed()throws Exception{
        var other=new TenantPrincipal(2L,"boss-b","",List.of(new SimpleGrantedAuthority("ROLE_SUPERVISOR")));var pool=Executors.newFixedThreadPool(2);var start=new CountDownLatch(1);
        try{Callable<Boolean> first=()->{start.await(5,TimeUnit.SECONDS);try{tx.execute(status->accounts.change(boss(),2,new AccountAccessService.Change(false,"SUPERVISOR",0L,"disable-other-b")));return true;}catch(org.springframework.security.core.AuthenticationException|org.springframework.security.access.AccessDeniedException expected){return false;}};
            Callable<Boolean> second=()->{start.await(5,TimeUnit.SECONDS);try{tx.execute(status->accounts.change(other,1,new AccountAccessService.Change(false,"SUPERVISOR",0L,"disable-other-a")));return true;}catch(org.springframework.security.core.AuthenticationException|org.springframework.security.access.AccessDeniedException expected){return false;}};
            var a=pool.submit(first);var b=pool.submit(second);start.countDown();assertThat(List.of(a.get(15,TimeUnit.SECONDS),b.get(15,TimeUnit.SECONDS))).containsExactlyInAnyOrder(true,false);
        }finally{start.countDown();pool.shutdownNow();}
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM users WHERE enabled=TRUE AND role='SUPERVISOR'",Integer.class)).isEqualTo(1);
    }
}
