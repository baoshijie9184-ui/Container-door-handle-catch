package com.ruanzhu.doorhandle.module.ai.model;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity;
import com.ruanzhu.doorhandle.module.ai.config.AgentModelProperties;
import com.ruanzhu.doorhandle.module.ai.testsupport.FeatureMySql;
import com.ruanzhu.doorhandle.module.ai.testsupport.CompactQuotaFixture;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import io.agentscope.core.message.TextBlock;
import io.agentscope.core.model.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import reactor.core.publisher.Flux;
import javax.sql.DataSource;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@TestInstance(TestInstance.Lifecycle.PER_CLASS)
@EnabledIfSystemProperty(named="doorhandle.feature.mysql.config",matches=".+")
class ModelBudgetMySqlTest {
    AnnotationConfigApplicationContext context;JdbcTemplate jdbc;ModelBudgetService service;Directory directory;CompactQuotaFixture fixture;
    final Map<String,ModelBudgetService.Ticket> tickets=new ConcurrentHashMap<>();
    static final String FIRST="dashscope:qwen-feature",SECOND="dashscope:glm-feature";
    @BeforeAll void start()throws Exception{context=new AnnotationConfigApplicationContext();context.getEnvironment().getPropertySources().addFirst(new org.springframework.core.env.MapPropertySource("budget-test",Map.of("app.model-budget.enabled","true")));context.register(Config.class,ModelBudgetService.class);context.refresh();jdbc=context.getBean(JdbcTemplate.class);service=context.getBean(ModelBudgetService.class);directory=context.getBean(Directory.class);fixture=new CompactQuotaFixture(context.getBean(DataSource.class));}
    @AfterAll void close(){try{if(fixture!=null)fixture.close();}finally{if(context!=null)context.close();}}
    @BeforeEach void reset(){jdbc.update("DELETE FROM audit_event");jdbc.update("DELETE FROM llm_usage");jdbc.update("DELETE FROM workflow_instance WHERE parent_workflow_id IS NOT NULL");jdbc.update("DELETE FROM workflow_instance");jdbc.update("DELETE FROM llm_quota");jdbc.update("DELETE FROM users");jdbc.update("INSERT INTO users(id,username,password) VALUES(3,'boss','fixture'),(4,'member','fixture')");tickets.clear();directory.roles.put(3L,true);directory.account.set(new Identity(3,"boss",true));}
    void policy(String id,long total){service.policy(new ModelBudgetService.Policy(id,total,80,null,0));}
    String key(){return UUID.randomUUID().toString();}
    Map<String,Object> usage(long input,long output){return Map.of("modelId",FIRST,"status","COMPLETED","inputTokens",input,"outputTokens",output,"cachedTokens",5);}
    Map<String,Object> entry(String id){return service.overview().stream().filter(row->row.get("model_id").equals(id)).findFirst().orElseThrow();}
    @Test void eachModelHasItsOwnQuotaAndCachedTokensAreNotChargedTwice(){policy(FIRST,1000);policy(SECOND,1000);start("attempt-one",FIRST);finish("attempt-one",usage(100,20));@SuppressWarnings("unchecked")var use=(Map<String,Object>)entry(FIRST).get("usage");assertThat(((Number)use.get("reportedTokens")).longValue()).isEqualTo(120);@SuppressWarnings("unchecked")var other=(Map<String,Object>)entry(SECOND).get("usage");assertThat(((Number)other.get("reportedTokens")).longValue()).isZero();assertThat(entry(FIRST).get("liveProviderRemaining")).isNull();assertThat(entry(FIRST).get("providerObservation")).isNull();}
    @Test void unknownUsageRemainsUnknownAndNoProviderBalanceIsInvented(){policy(FIRST,1_000_000);start("attempt-missing",FIRST);finish("attempt-missing",Map.of("modelId",FIRST,"status","FAILED"));var row=entry(FIRST);assertThat(row.get("alert")).isEqualTo("USAGE_INCOMPLETE");@SuppressWarnings("unchecked")var use=(Map<String,Object>)row.get("usage");assertThat(((Number)use.get("unknownAttempts")).longValue()).isEqualTo(1);assertThat(row.get("liveProviderRemaining")).isNull();}
    @Test void observationsAreAppendOnlyIdempotentAndCannotBeDefaultedToZero(){policy(FIRST,1000);assertThatThrownBy(()->service.observe(new ModelBudgetService.Observation(FIRST,null,OffsetDateTime.now(ZoneOffset.UTC),"控制台核对",key()))).isInstanceOf(BusinessException.class);var request=new ModelBudgetService.Observation(FIRST,10L,OffsetDateTime.now(ZoneOffset.UTC),"控制台实际余额","observation-repeat");service.observe(request);service.observe(request);assertThat(service.observations(FIRST)).hasSize(1);assertThat(entry(FIRST).get("alert")).isEqualTo("LAST_OBSERVATION_WARNING");assertThatThrownBy(()->service.observe(new ModelBudgetService.Observation(FIRST,20L,request.observedAt(),"不同余额",request.requestId()))).isInstanceOf(BusinessException.class);}
    @Test void stalePolicyAndRevokedRoleCannotChangeQuota(){policy(FIRST,1000);assertThatThrownBy(()->service.policy(new ModelBudgetService.Policy(FIRST,2000L,80,null,1))).isInstanceOf(BusinessException.class);directory.roles.put(3L,false);assertThatThrownBy(()->service.overview()).isInstanceOf(BusinessException.class);assertThatThrownBy(()->service.policy(new ModelBudgetService.Policy(FIRST,5000L,80,null,2))).isInstanceOf(BusinessException.class);assertThat(jdbc.queryForObject("SELECT total_tokens FROM llm_quota WHERE scope_type='MODEL' AND model_id=?",Long.class,FIRST)).isEqualTo(1000);}
    @Test void expiredAndExhaustedObservationsBlockOnlyTheirCandidate(){service.policy(new ModelBudgetService.Policy(FIRST,1000L,80,OffsetDateTime.now(ZoneOffset.UTC).minusHours(1),0));assertThatThrownBy(()->start("expired-attempt",FIRST)).isInstanceOf(ModelBudgetService.Exhausted.class);policy(SECOND,1000);service.observe(new ModelBudgetService.Observation(SECOND,0L,OffsetDateTime.now(ZoneOffset.UTC),"核对已耗尽",key()));assertThatThrownBy(()->start("empty-attempt",SECOND)).isInstanceOf(ModelBudgetService.Exhausted.class);assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='LLM_PROVIDER_ATTEMPT'",Long.class)).isZero();}
    @Test void routedFallbackRecordsActualCandidateWithoutCallingBlockedProvider(){policy(FIRST,0);policy(SECOND,1000);var primary=mock(Model.class);var fallback=mock(Model.class);when(primary.getModelName()).thenReturn("primary");when(fallback.getModelName()).thenReturn("backup");var response=ChatResponse.builder().content(List.of(TextBlock.builder().text("本地脚本响应").build())).build();when(fallback.stream(anyList(),anyList(),any())).thenReturn(Flux.just(response));var settings=new AgentModelProperties();settings.setMaxOutputTokens(64);var route=new ManagedAgentModel(List.of(new ManagedAgentModel.Candidate(FIRST,"dashscope",primary,circuit()),new ManagedAgentModel.Candidate(SECOND,"dashscope",fallback,circuit())),null,settings,true).budget(service);assertThat(routed(route)).isSameAs(response);verify(primary,never()).stream(anyList(),anyList(),any());verify(fallback,times(1)).stream(anyList(),anyList(),any());assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='LLM_PROVIDER_ATTEMPT' AND resource_id=?",Long.class,FIRST)).isZero();assertThat(jdbc.queryForObject("SELECT status FROM workflow_instance WHERE kind='LLM_PROVIDER_ATTEMPT' AND resource_id=?",String.class,SECOND)).isEqualTo("NEEDS_REVIEW");}
    @Test void failedLedgerCannotEmitAProviderRequestOrTryAnotherProvider(){policy(FIRST,1000);var primary=mock(Model.class);var fallback=mock(Model.class);when(primary.getModelName()).thenReturn("primary");when(fallback.getModelName()).thenReturn("backup");jdbc.execute("ALTER TABLE workflow_instance ADD CONSTRAINT deny_attempt CHECK(kind<>'LLM_PROVIDER_ATTEMPT' OR resource_id<>'"+FIRST+"')");try{var route=new ManagedAgentModel(List.of(new ManagedAgentModel.Candidate(FIRST,"dashscope",primary,circuit()),new ManagedAgentModel.Candidate(SECOND,"dashscope",fallback,circuit())),null,new AgentModelProperties(),true).budget(service);assertThatThrownBy(()->routed(route)).isInstanceOf(IllegalStateException.class);verify(primary,never()).stream(anyList(),anyList(),any());verify(fallback,never()).stream(anyList(),anyList(),any());}finally{jdbc.execute("ALTER TABLE workflow_instance DROP CHECK deny_attempt");}}
    @Test void concurrentObservationRetryHasOnlyOnePersistentCheckpoint()throws Exception{policy(FIRST,1000);var request=new ModelBudgetService.Observation(FIRST,900L,OffsetDateTime.now(ZoneOffset.UTC),"相同控制台核对","concurrent-observation");var pool=Executors.newFixedThreadPool(2);try{var a=pool.submit(()->service.observe(request));var b=pool.submit(()->service.observe(request));a.get(5,TimeUnit.SECONDS);b.get(5,TimeUnit.SECONDS);assertThat(service.observations(FIRST)).hasSize(1);}finally{pool.shutdownNow();}}
    @Test void concurrentCrossModelObservationIdentityHasOneWinnerAndOneBusinessConflict()throws Exception {
        policy(FIRST,1000);policy(SECOND,1000);
        var barrier=new CyclicBarrier(2);var entered=new java.util.concurrent.atomic.AtomicInteger();
        var gated=new JdbcTemplate(context.getBean(DataSource.class)) {
            @Override public int update(String sql,Object... args) {
                if(sql.contains("INSERT INTO audit_event")&&"MODEL_QUOTA_OBSERVATION".equals(args[1])) {
                    entered.incrementAndGet();
                    try {barrier.await(10,TimeUnit.SECONDS);}
                    catch(InterruptedException error){Thread.currentThread().interrupt();throw new IllegalStateException(error);}
                    catch(BrokenBarrierException|TimeoutException error){throw new IllegalStateException(error);}
                }
                return super.update(sql,args);
            }
        };
        var competing=new ModelBudgetService(gated,directory,context.getBean(ObjectMapper.class));
        var tx=new org.springframework.transaction.support.TransactionTemplate(new DataSourceTransactionManager(context.getBean(DataSource.class)));
        tx.setIsolationLevel(org.springframework.transaction.TransactionDefinition.ISOLATION_READ_COMMITTED);
        String request=key();var observed=OffsetDateTime.now(ZoneOffset.UTC);var pool=Executors.newFixedThreadPool(2);
        try {
            java.util.function.Function<String,Integer> write=model->{
                try {tx.executeWithoutResult(status->competing.observe(new ModelBudgetService.Observation(model,900L,observed,"并发供应商核对",request)));return 200;}
                catch(BusinessException conflict){return conflict.getCode();}
            };
            var first=pool.submit(()->write.apply(FIRST));var second=pool.submit(()->write.apply(SECOND));
            assertThat(List.of(first.get(15,TimeUnit.SECONDS),second.get(15,TimeUnit.SECONDS))).containsExactlyInAnyOrder(200,409);
        }finally{pool.shutdownNow();}
        // Both reached INSERT after the same empty-receipt check while holding the real shared identity lock.
        assertThat(entered).hasValue(2);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='MODEL_QUOTA_OBSERVATION'",Long.class)).isEqualTo(1);
        assertThat(service.observations(FIRST).size()+service.observations(SECOND).size()).isEqualTo(1);
    }
    @Test void identicalObservationCommittedAfterTheEmptyReadIsStillAnIdempotentReplay()throws Exception {
        policy(FIRST,1000);var winner=Executors.newSingleThreadExecutor();var inserted=new java.util.concurrent.atomic.AtomicBoolean();
        var gated=new JdbcTemplate(context.getBean(DataSource.class)) {
            @Override public int update(String sql,Object... args) {
                if(sql.contains("INSERT INTO audit_event")&&"MODEL_QUOTA_OBSERVATION".equals(args[1])&&inserted.compareAndSet(false,true)) {
                    // A separately committed immutable receipt arrives after this transaction's precheck.
                    Object[] winnerArgs=args.clone();winnerArgs[0]=UUID.randomUUID().toString();
                    try {winner.submit(()->jdbc.update(sql,winnerArgs)).get(10,TimeUnit.SECONDS);}
                    catch(InterruptedException error){Thread.currentThread().interrupt();throw new IllegalStateException(error);}
                    catch(ExecutionException|TimeoutException error){throw new IllegalStateException(error);}
                }
                return super.update(sql,args);
            }
        };
        var competing=new ModelBudgetService(gated,directory,context.getBean(ObjectMapper.class));
        var tx=new org.springframework.transaction.support.TransactionTemplate(new DataSourceTransactionManager(context.getBean(DataSource.class)));
        tx.setIsolationLevel(org.springframework.transaction.TransactionDefinition.ISOLATION_READ_COMMITTED);
        var request=new ModelBudgetService.Observation(FIRST,900L,OffsetDateTime.now(ZoneOffset.UTC),"核对回执先提交",key());
        try {tx.executeWithoutResult(status->competing.observe(request));}
        finally{winner.shutdownNow();}
        service.observe(request);assertThat(inserted).isTrue();assertThat(service.observations(FIRST)).hasSize(1);
    }
    @Test void httpJsonRegistrationAndObservationUseRequiredMarkerAndRealLedger()throws Exception{
        var http=org.springframework.test.web.servlet.setup.MockMvcBuilders.standaloneSetup(new com.ruanzhu.doorhandle.module.ai.api.ModelBudgetController(service)).setControllerAdvice(new com.ruanzhu.doorhandle.common.GlobalExceptionHandler()).build();
        var json=context.getBean(ObjectMapper.class);String body=json.writeValueAsString(new ModelBudgetService.Policy(FIRST,1000000L,80,null,0));
        http.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put("/api/agent/model-budgets").contentType("application/json").content(body)).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath("$.code").value(400));
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_quota",Long.class)).isZero();
        http.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put("/api/agent/model-budgets").header("X-Budget-Action","update").contentType("application/json").content(body)).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath("$.code").value(200));
        String observation="{\"modelId\":\""+FIRST+"\",\"remainingTokens\":900000,\"observedAt\":\"2026-01-01T08:00:00+08:00\",\"sourceNote\":\"控制台核对\",\"requestId\":\"http-observation-key\"}";
        http.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post("/api/agent/model-budgets/observations").header("X-Budget-Action","update").contentType("application/json").content(observation)).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath("$.code").value(200));
        assertThat(service.observations(FIRST)).hasSize(1);assertThat(service.observations(FIRST).get(0).get("observed_at")).isEqualTo(LocalDateTime.of(2026,1,1,0,0));
    }

    @Test void replayedAdmissionCannotAuthorizeAnotherProviderCall() {
        policy(FIRST,1000);String request=key(),attempt=key();
        var ticket=service.started(identity(),request,attempt,FIRST,200,"TEXT_UTF8_ESTIMATE_V1");
        assertThatThrownBy(()->service.started(identity(),request,attempt,FIRST,200,"TEXT_UTF8_ESTIMATE_V1"))
                .isInstanceOf(ModelAttemptTrace.RecordingException.class);
        assertThat(entry(FIRST)).containsEntry("reserved_tokens",200L);
        service.finished(ticket,usage(20,10));service.finished(ticket,usage(20,10));
        assertThat(entry(FIRST)).containsEntry("reserved_tokens",0L).containsEntry("spent_tokens",30L);
        assertThatThrownBy(()->service.finished(ticket,usage(20,11))).isInstanceOf(ModelAttemptTrace.RecordingException.class);
    }
    @Test void partialUsageOnFailureStaysReservedAndLogoutDoesNotEraseAccounting() {
        policy(FIRST,1000);var ticket=start("partial",FIRST);
        directory.roles.put(3L,false);
        var partial=Map.<String,Object>of("modelId",FIRST,"status","FAILED","inputTokens",20,"outputTokens",2);
        service.finished(ticket,partial);service.finished(ticket,partial);
        assertThat(jdbc.queryForMap("SELECT reserved_tokens,spent_tokens FROM llm_quota WHERE scope_type='MODEL'"))
                .containsEntry("reserved_tokens",200L).containsEntry("spent_tokens",0L);
        assertThat(jdbc.queryForObject("SELECT status FROM workflow_instance WHERE id=?",String.class,ticket.attemptId()))
                .isEqualTo("NEEDS_REVIEW");
        assertThatThrownBy(()->service.finished(ticket,usage(20,5))).isInstanceOf(ModelAttemptTrace.RecordingException.class);
    }
    @Test void serviceAppliesExistingPersonalQuotaAndDoesNotCreateOneImplicitly() {
        policy(FIRST,1000);start("before-grant",FIRST);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_quota WHERE scope_type='USER'",Long.class)).isZero();
        jdbc.update("INSERT INTO llm_quota(scope_type,owner_user_id,model_id,total_tokens,created_at,updated_at) VALUES('USER',3,?,300,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",FIRST);
        finish("before-grant",usage(20,10));start("after-grant",FIRST);
        finish("after-grant",usage(40,20));
        assertThat(jdbc.queryForMap("SELECT reserved_tokens,spent_tokens FROM llm_quota WHERE scope_type='USER'"))
                .containsEntry("reserved_tokens",0L).containsEntry("spent_tokens",60L);
        assertThat(entry(FIRST)).containsEntry("spent_tokens",90L);
    }
    @Test void admissionFailureRollsBackTheNewRequestAndBothBalances() {
        policy(FIRST,1000);
        jdbc.update("INSERT INTO llm_quota(scope_type,owner_user_id,model_id,total_tokens,created_at,updated_at) VALUES('USER',3,?,100,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",FIRST);
        assertThatThrownBy(()->start("too-large",FIRST)).isInstanceOf(ModelBudgetService.Exhausted.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind IN ('LLM_REQUEST','LLM_PROVIDER_ATTEMPT')",Long.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT SUM(reserved_tokens) FROM llm_quota",Long.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_usage WHERE entry_type='RESERVE'",Long.class)).isZero();
    }
    @Test void settlementFailureRollsBackBalancesAndLeavesAttemptUnconfirmed() {
        policy(FIRST,1000);var ticket=start("write-failure",FIRST);
        jdbc.execute("ALTER TABLE llm_usage ADD CONSTRAINT reject_settlement CHECK(entry_type<>'SETTLE')");
        try {
            assertThatThrownBy(()->service.finished(ticket,usage(20,10))).isInstanceOf(ModelAttemptTrace.RecordingException.class);
            assertThat(entry(FIRST)).containsEntry("reserved_tokens",200L).containsEntry("spent_tokens",0L);
            assertThat(jdbc.queryForObject("SELECT status FROM workflow_instance WHERE id=?",String.class,ticket.attemptId())).isEqualTo("STARTED");
        } finally {jdbc.execute("ALTER TABLE llm_usage DROP CHECK reject_settlement");}
        service.finished(ticket,usage(20,10));
        assertThat(entry(FIRST)).containsEntry("spent_tokens",30L).containsEntry("reserved_tokens",0L);
    }
    @Test void modelIdUsedByTheOfficialOpenAiAdapterCanHaveAQuota() {
        String id="openai-official:gpt-fixture";policy(id,1000);
        var ticket=start("official",id);
        service.finished(ticket,Map.of("modelId",id,"status","COMPLETED","inputTokens",10,"outputTokens",5));
        assertThat(entry(id)).containsEntry("spent_tokens",15L);
    }

    ModelBudgetContext identity(){return new ModelBudgetContext(new AgentActor(3,"boss",AgentActor.Role.SUPERVISOR),"quota-fixture-run");}
    ModelBudgetService.Ticket start(String key,String model){
        var ticket=service.started(identity(),UUID.randomUUID().toString(),UUID.randomUUID().toString(),model,200,"TEXT_UTF8_ESTIMATE_V1");
        tickets.put(key,ticket);return ticket;
    }
    void finish(String key,Map<String,Object> fields){service.finished(tickets.get(key),fields);}
    ChatResponse routed(ManagedAgentModel route){return route.stream(List.of(),List.of(),null)
            .contextWrite(ctx->ctx.put(ModelBudgetContext.CONTEXT_KEY,identity())).blockLast();}

    ModelCircuit circuit(){return new ModelCircuit(2,Duration.ofSeconds(1),Duration.ofSeconds(1));}
    static class Directory implements BusinessUserDirectory{final Map<Long,Boolean> roles=new ConcurrentHashMap<>(Map.of(3L,true));final ThreadLocal<Identity> account=ThreadLocal.withInitial(()->new Identity(3,"boss",true));public Identity authenticated(){return account.get();}public Identity current(long id,String name){return new Identity(id,name,roles.getOrDefault(id,false));}final JdbcTemplate jdbc;Directory(JdbcTemplate jdbc){this.jdbc=jdbc;}public Identity lockCurrent(long id,String name){jdbc.queryForObject("SELECT id FROM users WHERE id=? FOR SHARE",Long.class,id);return current(id,name);}}
    @Configuration @EnableTransactionManagement static class Config {
        @Bean DataSource source(){return FeatureMySql.source();}@Bean JdbcTemplate jdbc(DataSource source){return new JdbcTemplate(source);}@Bean DataSourceTransactionManager transactions(DataSource source){return new DataSourceTransactionManager(source);}@Bean Directory users(JdbcTemplate jdbc){return new Directory(jdbc);}@Bean ObjectMapper json(){return new ObjectMapper().findAndRegisterModules();}
    }
}
