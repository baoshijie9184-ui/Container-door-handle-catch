package com.ruanzhu.doorhandle.module.ai.model;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.collaboration.BusinessResourceChanged;
import com.ruanzhu.doorhandle.contracts.security.*;
import com.ruanzhu.doorhandle.module.ai.config.*;
import com.ruanzhu.doorhandle.module.ai.testsupport.*;
import com.ruanzhu.doorhandle.module.system.service.OperationsAuditService;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.context.annotation.*;
import org.springframework.core.env.MapPropertySource;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.mock.web.*;
import org.springframework.web.context.request.*;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import org.springframework.transaction.event.*;
import org.springframework.web.server.ResponseStatusException;
import javax.sql.DataSource;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.regex.Pattern;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** ECS admitted empty feature schema; real ledgers, V2 store and Spring commit events, zero provider calls. */
@EnabledIfSystemProperty(named="doorhandle.feature.mysql.config",matches=".+")
class AiCollaborationMySqlTest {
    static final String MODEL="dashscope:qwen-plus";
    static final AtomicBoolean REJECT=new AtomicBoolean();
    AnnotationConfigApplicationContext context;CompactQuotaFixture fixture;JdbcTemplate jdbc;Directory users;
    ModelConfigurationService config;ModelBudgetService budget;PersonalModelQuotaService personal;AiCollaborationResourceAccess access;
    OperationsAuditService history;Committed committed;Path privateDirectory;boolean configurationTable;
    @BeforeEach void open()throws Exception{
        var source=FeatureMySql.source();fixture=new CompactQuotaFixture(source);jdbc=new JdbcTemplate(source);
        String baseline=Files.readString(Path.of("../sql/mysql/compact/baseline/25-agent.sql"));
        var match=Pattern.compile("(?s)CREATE TABLE llm_configuration \\(.*?;(?=\\s*(?:--|CREATE|$))").matcher(baseline);
        if(!match.find())throw new IllegalStateException("Missing actual configuration baseline");
        new ResourceDatabasePopulator(new ByteArrayResource(match.group().getBytes(StandardCharsets.UTF_8))).execute(source);configurationTable=true;
        privateDirectory=Files.createTempDirectory(Files.createDirectories(Path.of("target")),"ai-collaboration-");
        Path key=privateDirectory.resolve("key");Files.writeString(key,Base64.getEncoder().encodeToString(new byte[32]));
        jdbc.update("INSERT INTO users(id,username,password,role,enabled) VALUES(1,'boss','fixture','SUPERVISOR',TRUE),(2,'other-boss','fixture','SUPERVISOR',TRUE),(3,'alice','fixture','INSPECTOR',TRUE),(4,'bob','fixture','INSPECTOR',TRUE)");
        REJECT.set(false);context=new AnnotationConfigApplicationContext();
        context.getEnvironment().getPropertySources().addFirst(new MapPropertySource("owned-ai-history",Map.of("app.model-budget.enabled","true","agentscope.model-config.enabled","true","operations.audit.enabled","true","collaboration.mutations.enabled","true","collaboration.change-history.enabled","true","fixture.key",key.toAbsolutePath().toString())));
        context.registerBean(DataSource.class,()->source);context.register(Config.class,ModelBudgetService.class,PersonalModelQuotaService.class);context.refresh();
        users=context.getBean(Directory.class);config=context.getBean(ModelConfigurationService.class);budget=context.getBean(ModelBudgetService.class);personal=context.getBean(PersonalModelQuotaService.class);
        access=context.getBean(AiCollaborationResourceAccess.class);history=context.getBean(OperationsAuditService.class);committed=context.getBean(Committed.class);
        when(context.getBean(MemoryModelConfigApi.class).appliedRevision()).thenAnswer(ignored->config.active().version());
    }
    @AfterEach void close()throws Exception{
        RequestContextHolder.resetRequestAttributes();
        try{if(context!=null)context.close();}finally{
            if(configurationTable)jdbc.execute("DROP TABLE llm_configuration");
            if(fixture!=null)fixture.close();
            if(privateDirectory!=null){Files.deleteIfExists(privateDirectory.resolve("key"));Files.deleteIfExists(privateDirectory);}
        }
    }
    AgentActor actor(long id){var current=users.current(id,id==1?"boss":id==2?"other-boss":id==3?"alice":"bob");return new AgentActor(id,current.username(),current.supervisor()?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR);}
    void as(long id){users.id.set(id);}
    long count(String kind){return jdbc.queryForObject("SELECT COUNT(*) FROM "+(kind.equals("OPERATIONS")?"audit_event":"workflow_instance")+" WHERE kind=?",Long.class,kind);}
    ModelConfigurationService.Draft draft(String request){return new ModelConfigurationService.Draft(config.active().version(),request,config.get(actor(1),config.active().version()).document(),Map.of());}
    ModelBudgetService.Policy policy(String request,long amount,long expected){return new ModelBudgetService.Policy(MODEL,amount,80,null,expected,request);}
    long quotaVersion(){return jdbc.queryForObject("SELECT version FROM llm_quota WHERE scope_type='MODEL' AND model_id=?",Long.class,MODEL);}
    PersonalModelQuotaService.Apply apply(String request){return new PersonalModelQuotaService.Apply(MODEL,90L,"private applicant explanation",request);}
    PersonalModelQuotaService.Decision approve(String request){return new PersonalModelQuotaService.Decision("APPROVE","private decision explanation",0L,request);}
    void business409(Runnable action){assertThatThrownBy(action::run).isInstanceOfSatisfying(BusinessException.class,error->assertThat(error.getCode()).isEqualTo(409));}
    void configuration409(Runnable action){assertThatThrownBy(action::run).isInstanceOfSatisfying(ResponseStatusException.class,error->assertThat(error.getStatusCode().value()).isEqualTo(409));}
    MockHttpServletResponse responseHeaders(){var response=new MockHttpServletResponse();RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(new MockHttpServletRequest(),response));return response;}

    @Test void configurationCommandsReplayOriginalResponsesAfterLaterStateTransitions(){
        var command=draft("config-draft-original");var headers=responseHeaders();var original=config.draft(actor(1),command);String auditId=headers.getHeader("X-Audit-ID");
        var validated=config.validate(actor(1),original.revision(),"config-validate-original");var published=config.publish(actor(1),original.revision(),"config-publish-original");
        var replay=responseHeaders();assertThat(config.draft(actor(1),command)).isEqualTo(original);assertThat(original.status()).isEqualTo("DRAFT");
        assertThat(replay.getHeader("X-Audit-ID")).isNotBlank().isEqualTo(auditId);assertThat(replay.getHeader("X-Resource-Version")).isEqualTo(original.changeVersion());
        assertThat(config.validate(actor(1),original.revision(),"config-validate-original")).isEqualTo(validated);
        assertThat(config.publish(actor(1),original.revision(),"config-publish-original")).isEqualTo(published);
        assertThat(config.get(actor(1),original.revision()).status()).isEqualTo("PUBLISHED");assertThat(count("MODEL_CONFIG_COMMAND")).isEqualTo(3);
    }
    @Test void changedConfigurationContentUnderTheSameRequestIsRejected(){
        var command=draft("config-conflict");config.draft(actor(1),command);
        configuration409(()->config.draft(actor(1),new ModelConfigurationService.Draft(command.baseRevision(),command.requestId(),command.document(),Map.of("dashscope","different-secret"))));
        assertThat(count("MODEL_CONFIG_COMMAND")).isEqualTo(1);
    }
    @Test void configurationAuditFailureRollsBackSnapshotCounterAndReceipt(){
        long version=jdbc.queryForObject("SELECT revision FROM runtime_state WHERE namespace='MODEL_CONFIG_CONTROL'",Long.class);REJECT.set(true);
        assertThatThrownBy(()->config.draft(actor(1),draft("failed-config-audit"))).hasMessage("required history unavailable");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_configuration",Long.class)).isEqualTo(1);assertThat(count("MODEL_CONFIG_COMMAND")).isZero();assertThat(committed.events).isEmpty();
        assertThat(jdbc.queryForObject("SELECT revision FROM runtime_state WHERE namespace='MODEL_CONFIG_CONTROL'",Long.class)).isEqualTo(version);
    }
    @Test void configurationPublicationAuditFailureDoesNotActivateOrRetireEitherSnapshot(){
        var candidate=config.draft(actor(1),draft("publish-failure-draft"));config.validate(actor(1),candidate.revision(),"publish-failure-validation");long records=count("MODEL_CONFIG_COMMAND");REJECT.set(true);
        assertThatThrownBy(()->config.publish(actor(1),candidate.revision(),"publish-failure")).hasMessage("required history unavailable");
        assertThat(config.active().version()).isEqualTo(1);assertThat(config.get(actor(1),candidate.revision()).status()).isEqualTo("VALIDATED");assertThat(count("MODEL_CONFIG_COMMAND")).isEqualTo(records);
    }
    @Test void credentialChangesHaveOnlyRedactedMarkersAndNeverPersistRawCredentials(){
        var command=draft("secret-config");var changed=config.draft(actor(1),new ModelConfigurationService.Draft(command.baseRevision(),command.requestId(),command.document(),Map.of("dashscope","new-fixture-secret")));
        String payload=jdbc.queryForObject("SELECT payload_json FROM audit_event WHERE kind='OPERATIONS' AND action='DRAFT'",String.class);
        assertThat(payload).contains("dashscopeCredential","CHANGED","\"redacted\":true").doesNotContain("new-fixture-secret","old-fixture-secret","api_key","base_url","sealed_snapshot");
        String response=jdbc.queryForObject("SELECT result_json FROM workflow_instance WHERE kind='MODEL_CONFIG_COMMAND' AND resource_id=?",String.class,Long.toString(changed.revision()));assertThat(response).doesNotContain("new-fixture-secret","old-fixture-secret");
    }
    @Test void jsonProbeRunsOnceAndItsActualOutcomeProducesDistinctVersionedHistory(){
        var candidate=config.draft(actor(1),draft("probe-draft"));var first=config.probeJson(actor(1),candidate.revision(),MODEL,"probe-once");assertThat(first.status()).isEqualTo("PASSED");
        assertThat(config.probeJson(actor(1),candidate.revision(),MODEL,"probe-once")).isEqualTo(first);verify(context.getBean(ModelJsonCompatibilityProbe.class),times(1)).check(any(),eq(MODEL));
        var versions=jdbc.queryForList("SELECT CAST(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.resourceVersion')) AS UNSIGNED) FROM audit_event WHERE kind='OPERATIONS' AND action='JSON_PROBE' ORDER BY id",Long.class);assertThat(versions).hasSize(2);assertThat(versions.get(1)).isGreaterThan(versions.get(0));
    }
    @Test void keyRevocationReplaysWithoutRepeatingHistoryAndCurrentAccessIsRechecked(){
        config.revoke(actor(1),"dashscope",1,"revoke-key-once");long records=count("OPERATIONS");config.revoke(actor(1),"dashscope",1,"revoke-key-once");assertThat(count("OPERATIONS")).isEqualTo(records);
        jdbc.update("UPDATE users SET role='INSPECTOR' WHERE id=1");assertThatThrownBy(()->config.revoke(new AgentActor(1,"boss",AgentActor.Role.SUPERVISOR),"dashscope",1,"revoke-key-once")).isInstanceOf(SecurityException.class);
    }
    @Test void legacyConfigurationReceiptWithoutAnOriginalResponseFailsClosed(){
        var candidate=config.draft(actor(1),draft("legacy-receipt-draft"));
        new org.springframework.transaction.support.TransactionTemplate(context.getBean(DataSourceTransactionManager.class)).executeWithoutResult(status->new ModelConfigurationStore(jdbc,context.getBean(ObjectMapper.class)).receipt(1,"old-validation","VALIDATE",Long.toString(candidate.revision()),candidate.revision()));
        configuration409(()->config.validate(actor(1),candidate.revision(),"old-validation"));assertThat(config.get(actor(1),candidate.revision()).status()).isEqualTo("DRAFT");
    }
    @Test void quotaPolicyReturnsItsOriginalSuccessAfterFurtherPolicyChanges(){
        as(1);var first=policy("policy-original",100,0);var original=responseHeaders();budget.policy(first);String audit=original.getHeader("X-Audit-ID"),resourceVersion=original.getHeader("X-Resource-Version");budget.policy(policy("policy-later",200,quotaVersion()));long version=quotaVersion(),events=count("OPERATIONS");
        var replay=responseHeaders();budget.policy(first);assertThat(replay.getHeader("X-Audit-ID")).isNotBlank().isEqualTo(audit);assertThat(replay.getHeader("X-Resource-Version")).isEqualTo(resourceVersion);assertThat(quotaVersion()).isEqualTo(version);assertThat(count("OPERATIONS")).isEqualTo(events);assertThat(count("LLM_QUOTA_CHANGE")).isEqualTo(2);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_usage WHERE entry_key='POLICY'",Long.class)).isEqualTo(2);
    }
    @Test void quotaRequestContentAndStaleVersionsConflictWithoutMoreLedgerEntries(){
        as(1);budget.policy(policy("quota-conflict",100,0));business409(()->budget.policy(policy("quota-conflict",200,0)));business409(()->budget.policy(policy("quota-stale",200,1)));assertThat(count("LLM_QUOTA_CHANGE")).isEqualTo(1);
    }
    @Test void requiredQuotaHistoryFailureRollsBackQuotaLedgerAndReceipt(){
        as(1);REJECT.set(true);assertThatThrownBy(()->budget.policy(policy("quota-failed-audit",100,0))).hasMessage("required history unavailable");
        assertThat(count("LLM_QUOTA_CHANGE")).isZero();assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_quota",Long.class)).isZero();assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_usage",Long.class)).isZero();assertThat(committed.events).isEmpty();
    }
    @Test void unchangedQuotaPolicyKeepsTheVersionAndOnlySavesAnIdempotentReceipt(){
        as(1);budget.policy(policy("quota-first",100,0));long version=quotaVersion(),events=count("OPERATIONS");budget.policy(policy("quota-no-change",100,version));budget.policy(policy("quota-no-change",100,version));assertThat(quotaVersion()).isEqualTo(version);assertThat(count("OPERATIONS")).isEqualTo(events);assertThat(count("LLM_QUOTA_CHANGE")).isEqualTo(2);
    }
    @Test void twoSupervisorsUpdatingTheSameQuotaVersionHaveOneWinner()throws Exception{
        as(1);budget.policy(policy("quota-initial",100,0));long version=quotaVersion();var start=new CountDownLatch(1);var pool=Executors.newFixedThreadPool(2);
        try{var outcomes=new ArrayList<Future<Boolean>>();for(long id:List.of(1L,2L))outcomes.add(pool.submit(()->{as(id);start.await(10,TimeUnit.SECONDS);try{budget.policy(policy("quota-race-"+id,200+id,version));return true;}catch(BusinessException conflict){assertThat(conflict.getCode()).isEqualTo(409);return false;}finally{users.id.remove();}}));start.countDown();assertThat(List.of(outcomes.get(0).get(20,TimeUnit.SECONDS),outcomes.get(1).get(20,TimeUnit.SECONDS))).containsExactlyInAnyOrder(true,false);}finally{pool.shutdownNow();}
        assertThat(count("LLM_QUOTA_CHANGE")).isEqualTo(2);assertThat(quotaVersion()).isEqualTo(version+1);
    }
    @Test void originalQuotaApplicationReplaysPendingEvenAfterAnApprovalWithoutAddingQuota(){
        as(3);var request=apply("application-original");var applyHeaders=responseHeaders();var original=personal.apply(request);String applyAudit=applyHeaders.getHeader("X-Audit-ID");assertThat(personal.mine().get(0).hasPersonalQuota()).isFalse();
        as(1);var approvalHeaders=responseHeaders();var approved=personal.decide(original.id(),approve("approval-original"));String approvalAudit=approvalHeaders.getHeader("X-Audit-ID");assertThat(approved.status()).isEqualTo("APPROVED");long events=count("OPERATIONS");
        var approvalReplay=responseHeaders();assertThat(personal.decide(original.id(),approve("approval-original"))).isEqualTo(approved);assertThat(approvalReplay.getHeader("X-Audit-ID")).isNotBlank().isEqualTo(approvalAudit);
        as(3);var applyReplay=responseHeaders();assertThat(personal.apply(request)).isEqualTo(original);assertThat(applyReplay.getHeader("X-Audit-ID")).isNotBlank().isEqualTo(applyAudit);assertThat(personal.mine().get(0).totalTokens()).isEqualTo(90);assertThat(count("OPERATIONS")).isEqualTo(events);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_usage WHERE entry_key='APPROVAL'",Long.class)).isEqualTo(1);
    }
    @Test void approvalHistoryFailureRollsBackGrantDecisionAndBothHistoryKinds(){
        as(3);var application=personal.apply(apply("application-failed-decision"));long events=count("OPERATIONS");as(1);REJECT.set(true);
        assertThatThrownBy(()->personal.decide(application.id(),approve("failed-grant-history"))).hasMessage("required history unavailable");
        assertThat(jdbc.queryForObject("SELECT status FROM workflow_instance WHERE workflow_id=?",String.class,application.id())).isEqualTo("PENDING");assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_quota WHERE scope_type='USER'",Long.class)).isZero();assertThat(count("OPERATIONS")).isEqualTo(events);
    }
    @Test void historyAndSseUseTheSameCurrentDomainAccessIncludingPrivateQuotaBalances(){
        as(3);var application=personal.apply(apply("application-authorized"));assertThat(access.mayRead(actor(3),"ENTERPRISE","LLM_QUOTA_APPLICATION","LLM_QUOTA_APPLICATION",application.id())).isTrue();assertThat(access.mayRead(actor(4),"ENTERPRISE","LLM_QUOTA_APPLICATION","LLM_QUOTA_APPLICATION",application.id())).isFalse();assertThat(access.mayRead(actor(1),"ENTERPRISE","LLM_QUOTA_APPLICATION","LLM_QUOTA_APPLICATION",application.id())).isTrue();
        as(1);personal.decide(application.id(),approve("approval-authorized"));String quota=jdbc.queryForObject("SELECT CAST(id AS CHAR) FROM llm_quota WHERE scope_type='USER' AND owner_user_id=3",String.class);
        assertThat(access.mayRead(actor(3),"ENTERPRISE","MODEL_BUDGET","LLM_PERSONAL_QUOTA",quota)).isTrue();assertThat(access.mayRead(actor(4),"ENTERPRISE","MODEL_BUDGET","LLM_PERSONAL_QUOTA",quota)).isFalse();assertThat(access.mayRead(actor(1),"ENTERPRISE","MODEL_BUDGET","LLM_PERSONAL_QUOTA",quota)).isFalse();
        jdbc.update("UPDATE users SET enabled=FALSE WHERE id=3");assertThat(access.mayRead(new AgentActor(3,"alice",AgentActor.Role.INSPECTOR),"ENTERPRISE","LLM_QUOTA_APPLICATION","LLM_QUOTA_APPLICATION",application.id())).isFalse();
    }
    @Test void committedAiChangesHaveRealV2IdentityTypedQuantitiesAndNoPrivateReasons(){
        as(3);var application=personal.apply(apply("application-public-fields"));as(1);personal.decide(application.id(),approve("approval-public-fields"));
        var payloads=jdbc.queryForList("SELECT payload_json FROM audit_event WHERE kind='OPERATIONS' ORDER BY id",String.class);assertThat(payloads).hasSize(3);
        assertThat(String.join("",payloads)).contains("actorUsername","actorRole","requestedTokens").doesNotContain("private applicant explanation","private decision explanation");
        assertThat(committed.events).hasSize(3);assertThat(committed.events).allSatisfy(event->assertThat(event.auditId()).isNotBlank());
    }
    @Test void enterprisePolicyRequiresClientRequestIdAndNeverGrantsMissingPersonalQuota(){
        as(1);assertThatThrownBy(()->budget.policy(new ModelBudgetService.Policy(MODEL,100L,80,null,0))).isInstanceOfSatisfying(BusinessException.class,error->assertThat(error.getCode()).isEqualTo(400));
        as(3);var entry=personal.mine().get(0);assertThat(entry.configured()).isTrue();assertThat(entry.hasPersonalQuota()).isFalse();assertThat(entry.availableTokens()).isNull();assertThat(count("LLM_QUOTA_CHANGE")).isZero();
        as(1);var request=new ModelBudgetService.Observation(MODEL,1000L,java.time.OffsetDateTime.now(java.time.ZoneOffset.UTC),"private observation source","observation-original");
        var first=responseHeaders();budget.observe(request);String original=first.getHeader("X-Audit-ID");var replay=responseHeaders();budget.observe(request);assertThat(replay.getHeader("X-Audit-ID")).isNotBlank().isEqualTo(original);
        assertThat(count("OPERATIONS")).isEqualTo(1);assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='MODEL_QUOTA_OBSERVATION'",Long.class)).isEqualTo(1);
    }

    static class Directory implements BusinessUserDirectory{
        final JdbcTemplate jdbc;final ThreadLocal<Long> id=ThreadLocal.withInitial(()->1L);Directory(JdbcTemplate jdbc){this.jdbc=jdbc;}
        public Identity authenticated(){return read(id.get(),null,false);}public Identity current(long id,String name){return read(id,name,false);}public Identity lockCurrent(long id,String name){return read(id,name,true);}
        Identity read(long id,String name,boolean lock){var rows=jdbc.queryForList("SELECT username,role,enabled FROM users WHERE id=?"+(lock?" FOR UPDATE":""),id);if(rows.size()!=1)throw new SecurityException();var row=rows.get(0);String username=row.get("username").toString();if(name!=null&&!name.equals(username)||!Boolean.TRUE.equals(row.get("enabled"))&&!(row.get("enabled") instanceof Number enabled&&enabled.intValue()==1))throw new SecurityException();return new Identity(id,username,"SUPERVISOR".equals(row.get("role")));}
    }
    static class Committed{final List<BusinessResourceChanged> events=new CopyOnWriteArrayList<>();@TransactionalEventListener(phase=TransactionPhase.AFTER_COMMIT)public void accept(BusinessResourceChanged event){events.add(event);}}
    @Configuration @EnableTransactionManagement(proxyTargetClass=true) static class Config{
        @Bean JdbcTemplate jdbc(DataSource source){return new JdbcTemplate(source);}@Bean DataSourceTransactionManager transactions(DataSource source){return new DataSourceTransactionManager(source);}
        @Bean Directory users(JdbcTemplate jdbc){return new Directory(jdbc);}@Bean ObjectMapper json(){return new ObjectMapper().findAndRegisterModules();}
        @Bean com.ruanzhu.doorhandle.module.system.mapper.AccountEmployeeBindingMapper bindings(){return mock(com.ruanzhu.doorhandle.module.system.mapper.AccountEmployeeBindingMapper.class);}
        @Bean com.ruanzhu.doorhandle.contracts.organization.EmployeeDirectoryApi employees(){return mock(com.ruanzhu.doorhandle.contracts.organization.EmployeeDirectoryApi.class);}
        @Bean AiCollaborationResourceAccess access(JdbcTemplate jdbc,Directory users){return new AiCollaborationResourceAccess(jdbc,users);}
        @Bean OperationsAuditService history(JdbcTemplate jdbc,Directory users,AiCollaborationResourceAccess access,ApplicationEventPublisher events){var history=new OperationsAuditService(jdbc,users);history.collaboration(List.of(access),events,null,null);ReflectionTestUtils.setField(history,"changeHistoryEnabled",true);return history;}
        @Bean @Primary OperationsAuditApi audit(OperationsAuditService delegate){return new OperationsAuditApi(){public void append(Event event){delegate.append(event);}public void appendChange(ChangeEvent event){appendChangeWithReceipt(event);}public ChangeReceipt appendChangeWithReceipt(ChangeEvent event){if(REJECT.get())throw new IllegalStateException("required history unavailable");return delegate.appendChangeWithReceipt(event);}public ChangeReceipt findChangeReceipt(AgentActor actor,String domain,String type,String id,String request){return delegate.findChangeReceipt(actor,domain,type,id,request);}};}
        @Bean AiCollaborationHistory collaboration(OperationsAuditApi audit){return new AiCollaborationHistory(audit);}
        @Bean Committed committed(){return new Committed();}@Bean MemoryModelConfigApi memory(){return mock(MemoryModelConfigApi.class);}
        @Bean ModelJsonCompatibilityProbe probe(){var probe=mock(ModelJsonCompatibilityProbe.class);when(probe.check(any(),anyString())).thenReturn(true);return probe;}
        @Bean AgentModelService models(){var model=mock(AgentModelService.class);when(model.entries()).thenReturn(List.of(new AgentModelService.ModelInfo(MODEL,"dashscope","qwen-plus","CHAT_COMPLETIONS",true,true,"CLOSED",null,0)));return model;}
        @Bean ModelConfigurationService configuration(JdbcTemplate jdbc,DataSourceTransactionManager tx,Directory users,OperationsAuditApi audit,ObjectMapper json,ObjectProvider<MemoryModelConfigApi> memory,@org.springframework.beans.factory.annotation.Value("${fixture.key}")String key){var props=new AgentModelProperties();props.getDashscope().setApiKey("old-fixture-secret");var agent=new AgentScopeProperties();agent.setModel(MODEL);return new ModelConfigurationService(jdbc,tx,users,audit,json,props,agent,memory,key,MODEL);}
    }
}
