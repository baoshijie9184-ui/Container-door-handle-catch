package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.collaboration.BusinessMutationParticipant;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import com.ruanzhu.doorhandle.module.system.support.OperationsMySqlFixture;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.api.*;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.transaction.*;
import org.springframework.transaction.annotation.*;
import org.springframework.web.context.request.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Real Spring proxies and admitted ECS MySQL transactions; audits must be atomic with the business write. */
@EnabledIfSystemProperty(named="doorhandle.operations.mysql.config",matches=".+")
class BusinessMutationAuditTest {
    AnnotationConfigApplicationContext context;
    JdbcTemplate jdbc;
    Mutations mutations;
    static final AtomicBoolean rejectAudit=new AtomicBoolean();
    static BusinessUserDirectory users;
    static OperationsMySqlFixture fixture;

    @Configuration @EnableAspectJAutoProxy(proxyTargetClass=true) @EnableTransactionManagement
    static class Config {
        @Bean JdbcTemplate jdbc(){return fixture.target();}
        @Bean PlatformTransactionManager transactions(JdbcTemplate jdbc){return new DataSourceTransactionManager(jdbc.getDataSource());}
        @Bean List<BusinessMutationParticipant> participants(){return List.of();}
        @Bean OperationsAuditApi audit(JdbcTemplate jdbc) throws Exception {
            fixture.install("CREATE TABLE business_record(id BIGINT PRIMARY KEY,changed INT NOT NULL);",";");jdbc.update("INSERT INTO business_record VALUES(1,0)");
            var delegate=new OperationsAuditService(jdbc,users);
            return event->{if(rejectAudit.get())throw new IllegalStateException("audit unavailable");delegate.append(event);};
        }
        @Bean BusinessMutationAudit aspect(OperationsAuditApi audit,PlatformTransactionManager tx){return new BusinessMutationAudit(audit,users,tx);}
        @Bean Mutations mutations(JdbcTemplate jdbc){return new Mutations(jdbc);}
    }
    static class Mutations {
        private final JdbcTemplate jdbc;
        Mutations(JdbcTemplate jdbc){this.jdbc=jdbc;}
        @BusinessMutation(domain="DETECTION",action="UPDATE") @Transactional
        public boolean update(long id){return jdbc.update("UPDATE business_record SET changed=changed+1 WHERE id=?",id)==1;}
        @BusinessMutation(domain="DETECTION",action="REJECT") @Transactional
        public void reject(long id){jdbc.update("UPDATE business_record SET changed=changed+1 WHERE id=?",id);throw new IllegalArgumentException("business rejected");}
    }
    @BeforeEach void setup() throws Exception {
        fixture=new OperationsMySqlFixture(false);
        users=mock(BusinessUserDirectory.class);when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",false));rejectAudit.set(false);
        context=new AnnotationConfigApplicationContext(Config.class);jdbc=context.getBean(JdbcTemplate.class);mutations=context.getBean(Mutations.class);
        var roles=List.of(new SimpleGrantedAuthority("ROLE_SUPERVISOR"));var principal=new TenantPrincipal(1L,"alice","",roles);
        SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken(principal,null,roles));
        var request=new MockHttpServletRequest();request.addHeader("X-Request-ID","atomic-request");RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
    }
    @AfterEach void close() throws Exception {SecurityContextHolder.clearContext();RequestContextHolder.resetRequestAttributes();if(context!=null)context.close();if(fixture!=null)fixture.close();}
    @Test void businessWriteAndSanitizedAuditCommitTogether(){
        assertThat(mutations.update(1)).isTrue();assertThat(jdbc.queryForObject("SELECT changed FROM business_record",Integer.class)).isEqualTo(1);
        var row=jdbc.queryForMap("SELECT actor_user_id,resource_id,request_id,operation_result AS result FROM audit_event WHERE kind='OPERATIONS'");
        assertThat(((Number)row.get("actor_user_id")).longValue()).isEqualTo(1);assertThat(row).containsEntry("resource_id","1").containsEntry("request_id","atomic-request").containsEntry("result","APPLIED");
    }
    @Test void auditFailureRollsBackTheActualBusinessTransaction(){
        rejectAudit.set(true);assertThatThrownBy(()->mutations.update(1)).hasMessage("audit unavailable");
        assertThat(jdbc.queryForObject("SELECT changed FROM business_record",Integer.class)).isZero();assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='OPERATIONS'",Integer.class)).isZero();
    }
    @Test void businessFailureDoesNotLeaveAnAppliedAuditOrPartiallyCommittedRow(){
        assertThatThrownBy(()->mutations.reject(1)).hasMessage("business rejected");
        assertThat(jdbc.queryForObject("SELECT changed FROM business_record",Integer.class)).isZero();assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='OPERATIONS'",Integer.class)).isZero();
    }
    @Test void noChangeResultIsNotReportedAsAnAppliedMutation(){
        assertThat(mutations.update(999)).isFalse();assertThat(jdbc.queryForObject("SELECT operation_result FROM audit_event WHERE kind='OPERATIONS'",String.class)).isEqualTo("NO_CHANGE");
    }
    @Test void revokedIdentityCannotMutateUsingAnOlderAuthenticationToken(){
        when(users.current(1,"alice")).thenThrow(new SecurityException("account revoked"));
        assertThatThrownBy(()->mutations.update(1)).isInstanceOf(SecurityException.class);assertThat(jdbc.queryForObject("SELECT changed FROM business_record",Integer.class)).isZero();
    }
}
