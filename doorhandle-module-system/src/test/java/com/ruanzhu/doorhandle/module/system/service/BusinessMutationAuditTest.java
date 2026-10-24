package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
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

/** Real Spring proxies and H2 transactions; audits must be atomic with the business write. */
class BusinessMutationAuditTest {
    AnnotationConfigApplicationContext context;
    JdbcTemplate jdbc;
    Mutations mutations;
    static final AtomicBoolean rejectAudit=new AtomicBoolean();
    static BusinessUserDirectory users;

    @Configuration @EnableAspectJAutoProxy(proxyTargetClass=true) @EnableTransactionManagement
    static class Config {
        @Bean JdbcTemplate jdbc(){return new JdbcTemplate(new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa",""));}
        @Bean PlatformTransactionManager transactions(JdbcTemplate jdbc){return new DataSourceTransactionManager(jdbc.getDataSource());}
        @Bean OperationsAuditApi audit(JdbcTemplate jdbc){
            jdbc.execute("CREATE TABLE business_record(id BIGINT PRIMARY KEY,changed INT NOT NULL)");jdbc.update("INSERT INTO business_record VALUES(1,0)");
            jdbc.execute("CREATE TABLE operations_audit(id BIGINT AUTO_INCREMENT PRIMARY KEY,actor_user_id BIGINT,scope VARCHAR(16),domain VARCHAR(48),action VARCHAR(64),resource_id VARCHAR(160),request_id VARCHAR(128),result VARCHAR(40),resource_version BIGINT,created_at TIMESTAMP,UNIQUE(actor_user_id,domain,action,resource_id,request_id,result))");
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
    @BeforeEach void setup(){
        users=mock(BusinessUserDirectory.class);when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",false));rejectAudit.set(false);
        context=new AnnotationConfigApplicationContext(Config.class);jdbc=context.getBean(JdbcTemplate.class);mutations=context.getBean(Mutations.class);
        var roles=List.of(new SimpleGrantedAuthority("ROLE_SUPERVISOR"));var principal=new TenantPrincipal(1L,"alice","",roles);
        SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken(principal,null,roles));
        var request=new MockHttpServletRequest();request.addHeader("X-Request-ID","atomic-request");RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
    }
    @AfterEach void close(){SecurityContextHolder.clearContext();RequestContextHolder.resetRequestAttributes();if(context!=null)context.close();}
    @Test void businessWriteAndSanitizedAuditCommitTogether(){
        assertThat(mutations.update(1)).isTrue();assertThat(jdbc.queryForObject("SELECT changed FROM business_record",Integer.class)).isEqualTo(1);
        var row=jdbc.queryForMap("SELECT actor_user_id,resource_id,request_id,result FROM operations_audit");
        assertThat(((Number)row.get("actor_user_id")).longValue()).isEqualTo(1);assertThat(row).containsEntry("resource_id","1").containsEntry("request_id","atomic-request").containsEntry("result","APPLIED");
    }
    @Test void auditFailureRollsBackTheActualBusinessTransaction(){
        rejectAudit.set(true);assertThatThrownBy(()->mutations.update(1)).hasMessage("audit unavailable");
        assertThat(jdbc.queryForObject("SELECT changed FROM business_record",Integer.class)).isZero();assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM operations_audit",Integer.class)).isZero();
    }
    @Test void businessFailureDoesNotLeaveAnAppliedAuditOrPartiallyCommittedRow(){
        assertThatThrownBy(()->mutations.reject(1)).hasMessage("business rejected");
        assertThat(jdbc.queryForObject("SELECT changed FROM business_record",Integer.class)).isZero();assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM operations_audit",Integer.class)).isZero();
    }
    @Test void noChangeResultIsNotReportedAsAnAppliedMutation(){
        assertThat(mutations.update(999)).isFalse();assertThat(jdbc.queryForObject("SELECT result FROM operations_audit",String.class)).isEqualTo("NO_CHANGE");
    }
    @Test void revokedIdentityCannotMutateUsingAnOlderAuthenticationToken(){
        when(users.current(1,"alice")).thenThrow(new SecurityException("account revoked"));
        assertThatThrownBy(()->mutations.update(1)).isInstanceOf(SecurityException.class);assertThat(jdbc.queryForObject("SELECT changed FROM business_record",Integer.class)).isZero();
    }
}
