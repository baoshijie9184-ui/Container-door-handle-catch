package com.ruanzhu.doorhandle.module.ai.model;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity;
import com.ruanzhu.doorhandle.module.ai.config.AgentModelProperties;
import com.ruanzhu.doorhandle.module.ai.testsupport.FeatureMySql;
import io.agentscope.core.message.TextBlock;
import io.agentscope.core.model.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
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
@EnabledIfEnvironmentVariable(named="DOORHANDLE_FEATURE_MYSQL_URL",matches="jdbc:mysql://127\\.0\\.0\\.1:13363/doorhandle_feature_.*")
class ModelBudgetMySqlTest {
    AnnotationConfigApplicationContext context;JdbcTemplate jdbc;ModelBudgetService service;Directory directory;
    static final String FIRST="dashscope:qwen-feature",SECOND="dashscope:glm-feature";
    @BeforeAll void start()throws Exception{context=new AnnotationConfigApplicationContext();context.getEnvironment().getPropertySources().addFirst(new org.springframework.core.env.MapPropertySource("budget-test",Map.of("app.model-budget.enabled","true")));context.register(Config.class,ModelBudgetService.class);context.refresh();jdbc=context.getBean(JdbcTemplate.class);service=context.getBean(ModelBudgetService.class);directory=context.getBean(Directory.class);FeatureMySql.migrate(context.getBean(DataSource.class),"migration-V64-model-budget.sql");FeatureMySql.migrate(context.getBean(DataSource.class),"migration-V64-model-budget.sql");}
    @AfterAll void close(){if(context!=null)context.close();}
    @BeforeEach void reset(){FeatureMySql.clear(jdbc,"agent_model_budget_audit","agent_model_budget_observation","agent_model_budget_attempt","agent_model_budget");directory.roles.put(3L,true);directory.account.set(new Identity(3,"boss",true));}
    void policy(String id,long total){service.policy(new ModelBudgetService.Policy(id,total,80,null,0));}
    String key(){return UUID.randomUUID().toString();}
    Map<String,Object> usage(long input,long output){return Map.of("modelId",FIRST,"status","COMPLETED","inputTokens",input,"outputTokens",output,"cachedTokens",5);}
    Map<String,Object> entry(String id){return service.overview().stream().filter(row->row.get("model_id").equals(id)).findFirst().orElseThrow();}
    @Test void eachModelHasItsOwnQuotaAndCachedTokensAreNotChargedTwice(){policy(FIRST,1000);policy(SECOND,1000);service.started("attempt-one",FIRST);service.finished("attempt-one",usage(100,20));@SuppressWarnings("unchecked")var use=(Map<String,Object>)entry(FIRST).get("usage");assertThat(((Number)use.get("reportedTokens")).longValue()).isEqualTo(120);@SuppressWarnings("unchecked")var other=(Map<String,Object>)entry(SECOND).get("usage");assertThat(((Number)other.get("reportedTokens")).longValue()).isZero();assertThat(entry(FIRST).get("liveProviderRemaining")).isNull();assertThat(entry(FIRST).get("providerObservation")).isNull();}
    @Test void unknownUsageRemainsUnknownAndNoProviderBalanceIsInvented(){policy(FIRST,1_000_000);service.started("attempt-missing",FIRST);service.finished("attempt-missing",Map.of("modelId",FIRST,"status","FAILED"));var row=entry(FIRST);assertThat(row.get("alert")).isEqualTo("USAGE_INCOMPLETE");@SuppressWarnings("unchecked")var use=(Map<String,Object>)row.get("usage");assertThat(((Number)use.get("unknownAttempts")).longValue()).isEqualTo(1);assertThat(row.get("liveProviderRemaining")).isNull();}
    @Test void observationsAreAppendOnlyIdempotentAndCannotBeDefaultedToZero(){policy(FIRST,1000);assertThatThrownBy(()->service.observe(new ModelBudgetService.Observation(FIRST,null,OffsetDateTime.now(ZoneOffset.UTC),"控制台核对",key()))).isInstanceOf(BusinessException.class);var request=new ModelBudgetService.Observation(FIRST,10L,OffsetDateTime.now(ZoneOffset.UTC),"控制台实际余额","observation-repeat");service.observe(request);service.observe(request);assertThat(service.observations(FIRST)).hasSize(1);assertThat(entry(FIRST).get("alert")).isEqualTo("LAST_OBSERVATION_WARNING");assertThatThrownBy(()->service.observe(new ModelBudgetService.Observation(FIRST,20L,request.observedAt(),"不同余额",request.requestId()))).isInstanceOf(BusinessException.class);}
    @Test void stalePolicyAndRevokedRoleCannotChangeQuota(){policy(FIRST,1000);assertThatThrownBy(()->service.policy(new ModelBudgetService.Policy(FIRST,2000L,80,null,1))).isInstanceOf(BusinessException.class);directory.roles.put(3L,false);assertThatThrownBy(()->service.overview()).isInstanceOf(BusinessException.class);assertThatThrownBy(()->service.policy(new ModelBudgetService.Policy(FIRST,5000L,80,null,2))).isInstanceOf(BusinessException.class);assertThat(jdbc.queryForObject("SELECT total_tokens FROM agent_model_budget WHERE model_id=?",Long.class,FIRST)).isEqualTo(1000);}
    @Test void expiredAndExhaustedObservationsBlockOnlyTheirCandidate(){service.policy(new ModelBudgetService.Policy(FIRST,1000L,80,OffsetDateTime.now(ZoneOffset.UTC).minusHours(1),0));assertThatThrownBy(()->service.started("expired-attempt",FIRST)).isInstanceOf(ModelBudgetService.Exhausted.class);policy(SECOND,1000);service.observe(new ModelBudgetService.Observation(SECOND,0L,OffsetDateTime.now(ZoneOffset.UTC),"核对已耗尽",key()));assertThatThrownBy(()->service.started("empty-attempt",SECOND)).isInstanceOf(ModelBudgetService.Exhausted.class);assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_model_budget_attempt",Long.class)).isZero();}
    @Test void routedFallbackRecordsActualCandidateWithoutCallingBlockedProvider(){policy(FIRST,0);policy(SECOND,1000);var primary=mock(Model.class);var fallback=mock(Model.class);when(primary.getModelName()).thenReturn("primary");when(fallback.getModelName()).thenReturn("backup");var response=ChatResponse.builder().content(List.of(TextBlock.builder().text("本地脚本响应").build())).build();when(fallback.stream(anyList(),anyList(),any())).thenReturn(Flux.just(response));var settings=new AgentModelProperties();var route=new ManagedAgentModel(List.of(new ManagedAgentModel.Candidate(FIRST,"dashscope",primary,circuit()),new ManagedAgentModel.Candidate(SECOND,"dashscope",fallback,circuit())),null,settings,true).budget(service);assertThat(route.stream(List.of(),List.of(),null).blockLast()).isSameAs(response);verify(primary,never()).stream(anyList(),anyList(),any());verify(fallback,times(1)).stream(anyList(),anyList(),any());assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_model_budget_attempt WHERE model_id=?",Long.class,FIRST)).isZero();assertThat(jdbc.queryForObject("SELECT status FROM agent_model_budget_attempt WHERE model_id=?",String.class,SECOND)).isEqualTo("COMPLETED");}
    @Test void failedLedgerCannotEmitAProviderRequestOrTryAnotherProvider(){policy(FIRST,1000);var primary=mock(Model.class);var fallback=mock(Model.class);when(primary.getModelName()).thenReturn("primary");when(fallback.getModelName()).thenReturn("backup");jdbc.execute("ALTER TABLE agent_model_budget_attempt ADD CONSTRAINT deny_attempt CHECK(model_id<>'"+FIRST+"')");try{var route=new ManagedAgentModel(List.of(new ManagedAgentModel.Candidate(FIRST,"dashscope",primary,circuit()),new ManagedAgentModel.Candidate(SECOND,"dashscope",fallback,circuit())),null,new AgentModelProperties(),true).budget(service);assertThatThrownBy(()->route.stream(List.of(),List.of(),null).blockLast()).isInstanceOf(IllegalStateException.class);verify(primary,never()).stream(anyList(),anyList(),any());verify(fallback,never()).stream(anyList(),anyList(),any());}finally{jdbc.execute("ALTER TABLE agent_model_budget_attempt DROP CHECK deny_attempt");}}
    @Test void concurrentObservationRetryHasOnlyOnePersistentCheckpoint()throws Exception{policy(FIRST,1000);var request=new ModelBudgetService.Observation(FIRST,900L,OffsetDateTime.now(ZoneOffset.UTC),"相同控制台核对","concurrent-observation");var pool=Executors.newFixedThreadPool(2);try{var a=pool.submit(()->service.observe(request));var b=pool.submit(()->service.observe(request));a.get(5,TimeUnit.SECONDS);b.get(5,TimeUnit.SECONDS);assertThat(service.observations(FIRST)).hasSize(1);}finally{pool.shutdownNow();}}
    @Test void httpJsonRegistrationAndObservationUseRequiredMarkerAndRealLedger()throws Exception{
        var http=org.springframework.test.web.servlet.setup.MockMvcBuilders.standaloneSetup(new com.ruanzhu.doorhandle.module.ai.api.ModelBudgetController(service)).setControllerAdvice(new com.ruanzhu.doorhandle.common.GlobalExceptionHandler()).build();
        var json=context.getBean(ObjectMapper.class);String body=json.writeValueAsString(new ModelBudgetService.Policy(FIRST,1000000L,80,null,0));
        http.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put("/api/agent/model-budgets").contentType("application/json").content(body)).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath("$.code").value(400));
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_model_budget",Long.class)).isZero();
        http.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put("/api/agent/model-budgets").header("X-Budget-Action","update").contentType("application/json").content(body)).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath("$.code").value(200));
        String observation="{\"modelId\":\""+FIRST+"\",\"remainingTokens\":900000,\"observedAt\":\"2026-01-01T08:00:00+08:00\",\"sourceNote\":\"控制台核对\",\"requestId\":\"http-observation-key\"}";
        http.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post("/api/agent/model-budgets/observations").header("X-Budget-Action","update").contentType("application/json").content(observation)).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath("$.code").value(200));
        assertThat(service.observations(FIRST)).hasSize(1);assertThat(service.observations(FIRST).get(0).get("observed_at")).isEqualTo(LocalDateTime.of(2026,1,1,0,0));
    }
    ModelCircuit circuit(){return new ModelCircuit(2,Duration.ofSeconds(1),Duration.ofSeconds(1));}
    static class Directory implements BusinessUserDirectory{final Map<Long,Boolean> roles=new ConcurrentHashMap<>(Map.of(3L,true));final ThreadLocal<Identity> account=ThreadLocal.withInitial(()->new Identity(3,"boss",true));public Identity authenticated(){return account.get();}public Identity current(long id,String name){return new Identity(id,name,roles.getOrDefault(id,false));}public Identity lockCurrent(long id,String name){return current(id,name);}}
    @Configuration @EnableTransactionManagement static class Config {
        @Bean DataSource source(){return FeatureMySql.source();}@Bean JdbcTemplate jdbc(DataSource source){return new JdbcTemplate(source);}@Bean DataSourceTransactionManager transactions(DataSource source){return new DataSourceTransactionManager(source);}@Bean Directory users(){return new Directory();}@Bean ObjectMapper json(){return new ObjectMapper().findAndRegisterModules();}
    }
}
