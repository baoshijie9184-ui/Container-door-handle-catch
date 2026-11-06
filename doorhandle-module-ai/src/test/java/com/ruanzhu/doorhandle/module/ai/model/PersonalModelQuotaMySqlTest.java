package com.ruanzhu.doorhandle.module.ai.model;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.api.PersonalModelQuotaController;
import com.ruanzhu.doorhandle.module.ai.testsupport.CompactQuotaFixture;
import com.ruanzhu.doorhandle.module.ai.testsupport.FeatureMySql;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.sql.DataSource;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/** Native transactions, FK protection and concurrent approval. Requires the existing ECS identity admission. */
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
@EnabledIfSystemProperty(named="doorhandle.feature.mysql.config",matches=".+")
class PersonalModelQuotaMySqlTest {
    static final String MODEL="dashscope:qwen-personal-fixture";
    static final AtomicBoolean CONFIGURED=new AtomicBoolean(true);
    AnnotationConfigApplicationContext context;CompactQuotaFixture fixture;JdbcTemplate jdbc;
    PersonalModelQuotaService service;Directory users;

    @BeforeAll void start() {
        context=new AnnotationConfigApplicationContext();
        context.getEnvironment().getPropertySources().addFirst(new org.springframework.core.env.MapPropertySource("quota-test",Map.of("app.model-budget.enabled","true")));
        context.register(Config.class,PersonalModelQuotaService.class);context.refresh();
        jdbc=context.getBean(JdbcTemplate.class);service=context.getBean(PersonalModelQuotaService.class);users=context.getBean(Directory.class);
    }
    @BeforeEach void setup()throws Exception {
        fixture=new CompactQuotaFixture(context.getBean(DataSource.class));CONFIGURED.set(true);
        jdbc.update("INSERT INTO users(id,username,password,role) VALUES(3,'boss','fixture','SUPERVISOR'),(4,'alice','fixture','INSPECTOR'),(5,'bob','fixture','OPERATOR'),(6,'admin','fixture','ADMIN')");
        as(4);
    }
    @AfterEach void clean(){if(fixture!=null){fixture.close();fixture=null;}users.identity.remove();}
    @AfterAll void stop(){if(context!=null)context.close();}
    void as(long id){users.identity.set(id);}
    String key(){return UUID.randomUUID().toString();}
    PersonalModelQuotaService.Apply request(long tokens){return new PersonalModelQuotaService.Apply(MODEL,tokens,"质检工作需要",key());}
    PersonalModelQuotaService.Application apply(long tokens){return service.apply(request(tokens));}
    PersonalModelQuotaService.Decision approval(String key){return new PersonalModelQuotaService.Decision("APPROVE","同意新增工作额度",0L,key);}
    Map<String,Object> account(long owner){return jdbc.queryForMap("SELECT total_tokens,reserved_tokens,spent_tokens,version FROM llm_quota WHERE scope_type='USER' AND owner_user_id=?",owner);}
    void failure(Runnable operation,int code){assertThatThrownBy(operation::run).isInstanceOfSatisfying(BusinessException.class,error->assertThat(error.getCode()).isEqualTo(code));}

    @Test void absentPersonalQuotaPreservesPermissionAndApplicationDoesNotGrantEarly() {
        var mine=service.mine().get(0);assertThat(mine.configured()).isTrue();assertThat(mine.hasPersonalQuota()).isFalse();
        assertThat(mine.totalTokens()).isNull();assertThat(mine.availableTokens()).isNull();
        assertThat(mine.reservedTokens()).isZero();assertThat(mine.spentTokens()).isZero();
        var request=request(100);var application=service.apply(request);
        assertThat(service.apply(request).id()).isEqualTo(application.id());
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_quota WHERE scope_type='USER'",Long.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='LLM_QUOTA_APPLICATION'",Long.class)).isEqualTo(1);
        failure(()->service.apply(new PersonalModelQuotaService.Apply(MODEL,101L,request.reason(),request.requestId())),409);
    }
    @Test void approvalAddsTokensWithoutResettingUsageOrMovingEnterpriseTokens() {
        jdbc.update("INSERT INTO llm_quota(scope_type,model_id,total_tokens,created_at,updated_at) VALUES('MODEL',?,1000,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",MODEL);
        jdbc.update("INSERT INTO llm_quota(scope_type,owner_user_id,model_id,total_tokens,reserved_tokens,spent_tokens,version,created_at,updated_at) VALUES('USER',4,?,100,15,20,7,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",MODEL);
        var application=apply(50);as(3);var command=approval(key());
        var approved=service.decide(application.id(),command);
        assertThat(approved.status()).isEqualTo("APPROVED");assertThat(approved.deciderUserId()).isEqualTo(3L);
        assertThat(service.decide(application.id(),command)).isEqualTo(approved);
        assertThat(account(4)).containsEntry("total_tokens",150L).containsEntry("reserved_tokens",15L).containsEntry("spent_tokens",20L).containsEntry("version",8L);
        assertThat(jdbc.queryForObject("SELECT total_tokens FROM llm_quota WHERE scope_type='MODEL'",Long.class)).isEqualTo(1000);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_usage WHERE entry_type='LIMIT_CHANGE'",Long.class)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE action='APPROVE'",Long.class)).isEqualTo(1);
        failure(()->service.decide(application.id(),approval(key())),409);
        assertThatThrownBy(()->jdbc.update("DELETE FROM users WHERE id=3")).isInstanceOf(org.springframework.dao.DataAccessException.class);
    }
    @Test void supervisorRoleIsRefreshedAndMembersCannotReadOrDecideTeamApplications() {
        var application=apply(50);failure(()->service.applications("team",null,Long.MAX_VALUE,20),403);
        failure(()->service.decide(application.id(),approval(key())),403);
        as(3);jdbc.update("UPDATE users SET role='INSPECTOR' WHERE id=3");
        failure(()->service.decide(application.id(),approval(key())),403);
        as(6);assertThat(service.decide(application.id(),approval(key())).status()).isEqualTo("APPROVED");
    }
    @Test void disabledModelsAndExistingUnlimitedPersonalAccountsCannotReceiveNewGrants() {
        CONFIGURED.set(false);failure(()->apply(50),409);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance",Long.class)).isZero();
        CONFIGURED.set(true);var application=apply(50);CONFIGURED.set(false);as(3);
        failure(()->service.decide(application.id(),approval(key())),409);
        CONFIGURED.set(true);
        jdbc.update("INSERT INTO llm_quota(scope_type,owner_user_id,model_id,total_tokens,created_at,updated_at) VALUES('USER',4,?,NULL,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",MODEL);
        failure(()->service.decide(application.id(),approval(key())),409);as(4);failure(()->apply(20),409);
        var mine=service.mine().get(0);assertThat(mine.hasPersonalQuota()).isTrue();assertThat(mine.totalTokens()).isNull();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_usage",Long.class)).isZero();
    }
    @Test void onlyApplicantCanCancelAndStaleDecisionsCannotGrant() {
        var application=apply(50);as(5);failure(()->service.cancel(application.id(),new PersonalModelQuotaService.Cancel(0L,key())),403);
        as(4);var cancel=new PersonalModelQuotaService.Cancel(0L,key());
        assertThat(service.cancel(application.id(),cancel).status()).isEqualTo("CANCELLED");
        assertThat(service.cancel(application.id(),cancel).version()).isEqualTo(1);
        as(3);failure(()->service.decide(application.id(),approval(key())),409);
        as(4);var pending=apply(20);as(3);
        failure(()->service.decide(pending.id(),new PersonalModelQuotaService.Decision("APPROVE","同意",1L,key())),409);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_quota WHERE scope_type='USER'",Long.class)).isZero();
    }
    @Test void privatePagesAreBoundedAndTeamStatusFilterHasStableCursor() {
        var alice=apply(10);as(5);var bob=apply(20);as(4);
        assertThat(service.applications("mine",null,Long.MAX_VALUE,20).items()).extracting(PersonalModelQuotaService.Application::id).containsExactly(alice.id());
        failure(()->service.applications("mine",null,Long.MAX_VALUE,101),400);
        as(3);var first=service.applications("team","PENDING",Long.MAX_VALUE,1);
        assertThat(first.items()).extracting(PersonalModelQuotaService.Application::id).containsExactly(bob.id());assertThat(first.nextCursor()).isNotNull();
        assertThat(service.applications("team","PENDING",first.nextCursor(),1).items()).extracting(PersonalModelQuotaService.Application::id).containsExactly(alice.id());
        service.decide(bob.id(),new PersonalModelQuotaService.Decision("REJECT","当前不需要增加",0L,key()));
        assertThat(service.applications("team","PENDING",Long.MAX_VALUE,20).items()).hasSize(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_usage",Long.class)).isZero();
    }
    @Test void decisionRequestCannotBeReusedForAnotherApplication() {
        var first=apply(10);var second=apply(20);as(3);var decision=approval(key());
        service.decide(first.id(),decision);failure(()->service.decide(second.id(),decision),409);
        assertThat(account(4)).containsEntry("total_tokens",10L);
    }
    @Test void concurrentIdenticalApprovalHasOneGrantAndOnePermanentReceipt()throws Exception {
        var application=apply(70);var command=approval(key());var pool=Executors.newFixedThreadPool(2);var start=new CountDownLatch(1);
        try {
            Callable<PersonalModelQuotaService.Application> approve=()->{as(3);start.await();return service.decide(application.id(),command);};
            var first=pool.submit(approve);var second=pool.submit(approve);start.countDown();
            assertThat(first.get(10,TimeUnit.SECONDS).id()).isEqualTo(second.get(10,TimeUnit.SECONDS).id());
        }finally{pool.shutdownNow();}
        assertThat(account(4)).containsEntry("total_tokens",70L);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_usage",Long.class)).isEqualTo(1);
    }
    @Test void oppositeSupervisorApprovalsUseTheSameUserLockOrder()throws Exception {
        as(3);var boss=apply(10);as(6);var admin=apply(20);
        var pool=Executors.newFixedThreadPool(2);var start=new CountDownLatch(1);
        try {
            var first=pool.submit(()->{as(3);start.await();return service.decide(admin.id(),approval(key()));});
            var second=pool.submit(()->{as(6);start.await();return service.decide(boss.id(),approval(key()));});
            start.countDown();assertThat(first.get(10,TimeUnit.SECONDS).status()).isEqualTo("APPROVED");
            assertThat(second.get(10,TimeUnit.SECONDS).status()).isEqualTo("APPROVED");
        }finally{pool.shutdownNow();}
        assertThat(account(3)).containsEntry("total_tokens",10L);assertThat(account(6)).containsEntry("total_tokens",20L);
    }
    @Test void auditFailureRollsBackGrantLedgerAndDecisionTogether() {
        var application=apply(90);as(3);
        jdbc.execute("CREATE TRIGGER fixture_reject_quota_decision BEFORE INSERT ON audit_event FOR EACH ROW BEGIN IF NEW.kind='LLM_QUOTA_APPLICATION' AND NEW.action='APPROVE' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fixture approval audit failure'; END IF; END");
        assertThatThrownBy(()->service.decide(application.id(),approval(key()))).isInstanceOf(RuntimeException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_quota WHERE scope_type='USER'",Long.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_usage",Long.class)).isZero();
        assertThat(jdbc.queryForMap("SELECT status,revision,decider_user_id FROM workflow_instance WHERE workflow_id=?",application.id()))
                .containsEntry("status","PENDING").containsEntry("revision",0L).containsEntry("decider_user_id",null);
    }
    @Test void enterpriseHistoricalUncertaintyIsShownSeparatelyFromPersonalRemaining() {
        jdbc.update("INSERT INTO llm_quota(scope_type,model_id,total_tokens,unreconciled_legacy_attempts,created_at,updated_at) VALUES('MODEL',?,100,1,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",MODEL);
        jdbc.update("INSERT INTO llm_quota(scope_type,owner_user_id,model_id,total_tokens,created_at,updated_at) VALUES('USER',4,?,50,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",MODEL);
        var mine=service.mine().get(0);assertThat(mine.availableTokens()).isEqualTo(50);assertThat(mine.enterpriseBlockedReason()).isEqualTo("HISTORY_UNRECONCILED");
    }
    @Test void httpRequiresMutationMarkerAndExactIntegersAndDisablesCaching()throws Exception {
        var http=org.springframework.test.web.servlet.setup.MockMvcBuilders.standaloneSetup(new PersonalModelQuotaController(service))
                .setControllerAdvice(new com.ruanzhu.doorhandle.common.GlobalExceptionHandler()).build();
        String body=context.getBean(ObjectMapper.class).writeValueAsString(request(10));
        http.perform(get("/api/agent/model-quotas/mine")).andExpect(jsonPath("$.code").value(200)).andExpect(header().string("Cache-Control","private, no-store"));
        http.perform(post("/api/agent/model-quotas/applications").contentType("application/json").content(body)).andExpect(jsonPath("$.code").value(400));
        http.perform(post("/api/agent/model-quotas/applications").header("X-Budget-Action","update").contentType("application/json").content(body.replace("\"requestedTokens\":10","\"requestedTokens\":10.5")))
                .andExpect(jsonPath("$.code").value(400));
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance",Long.class)).isZero();
        http.perform(post("/api/agent/model-quotas/applications").header("X-Budget-Action","update").contentType("application/json").content(body))
                .andExpect(jsonPath("$.code").value(200)).andExpect(jsonPath("$.data.status").value("PENDING"));
    }

    static final class Directory implements BusinessUserDirectory {
        final JdbcTemplate jdbc;final ThreadLocal<Long> identity=ThreadLocal.withInitial(()->4L);
        Directory(JdbcTemplate jdbc){this.jdbc=jdbc;}
        public Identity authenticated(){return read(identity.get(),null,false);}
        public Identity current(long id,String name){return read(id,name,false);}
        public Identity lockCurrent(long id,String name){return read(id,name,true);}
        private Identity read(long id,String name,boolean lock) {
            var row=jdbc.queryForMap("SELECT username,role FROM users WHERE id=?"+(lock?" FOR SHARE":""),id);
            String username=row.get("username").toString();if(name!=null&&!name.equals(username))throw new SecurityException();
            return new Identity(id,username,Set.of("SUPERVISOR","ADMIN").contains(row.get("role")));
        }
    }
    @Configuration @EnableTransactionManagement static class Config {
        @Bean DataSource source(){return FeatureMySql.source();}
        @Bean JdbcTemplate jdbc(DataSource source){return new JdbcTemplate(source);}
        @Bean DataSourceTransactionManager transactions(DataSource source){return new DataSourceTransactionManager(source);}
        @Bean Directory users(JdbcTemplate jdbc){return new Directory(jdbc);}
        @Bean ObjectMapper json(){return new ObjectMapper().findAndRegisterModules();}
        @Bean AgentModelService models(){var result=mock(AgentModelService.class);when(result.entries()).thenAnswer(ignored->List.of(
                new AgentModelService.ModelInfo(MODEL,"dashscope","qwen-personal-fixture","CHAT_COMPLETIONS",CONFIGURED.get(),true,"CLOSED",null,0)));return result;}
    }
}
