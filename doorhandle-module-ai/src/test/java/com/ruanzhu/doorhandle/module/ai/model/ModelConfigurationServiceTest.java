package com.ruanzhu.doorhandle.module.ai.model;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.config.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.support.StaticListableBeanFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class ModelConfigurationServiceTest {
    @TempDir Path directory;
    JdbcTemplate jdbc;
    BusinessUserDirectory users;
    OperationsAuditApi audit;
    MemoryModelConfigApi memory;
    ModelJsonCompatibilityProbe probe;
    ModelConfigurationService service;
    AgentModelProperties props;
    AgentScopeProperties agent;
    ObjectMapper json=new ObjectMapper().findAndRegisterModules();
    AgentActor boss=new AgentActor(3,"boss",AgentActor.Role.SUPERVISOR);
    AgentActor worker=new AgentActor(4,"worker",AgentActor.Role.INSPECTOR);
    Path keyFile;

    @BeforeEach void setup() throws Exception {
        var dataSource=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa","");
        boolean mysql=System.getProperty("agent.model-config.mysql-file")!=null;
        if(mysql) dataSource=com.ruanzhu.doorhandle.module.ai.EcsIsolatedMysql.open(
                System.getProperty("agent.model-config.mysql-file"), "doorhandle_model_verify_");
        jdbc=new JdbcTemplate(dataSource);
        com.ruanzhu.doorhandle.module.ai.testsupport.CompactModelConfigurationFixture.install(jdbc);
        users=mock(BusinessUserDirectory.class);
        when(users.current(3,"boss")).thenReturn(new BusinessUserDirectory.Identity(3,"boss",true));
        when(users.current(4,"worker")).thenReturn(new BusinessUserDirectory.Identity(4,"worker",false));
        audit=mock(OperationsAuditApi.class);memory=mock(MemoryModelConfigApi.class);probe=mock(ModelJsonCompatibilityProbe.class);
        props=new AgentModelProperties();props.getDashscope().setApiKey("fixture-old-key");props.setFallbackEnabled(true);props.setFallbackModels(List.of("dashscope:glm-fixture"));props.getDashscope().setAdditionalModels(List.of("glm-fixture"));
        agent=new AgentScopeProperties();agent.setModel("dashscope:qwen-plus");
        keyFile=directory.resolve("master.key");Files.writeString(keyFile,Base64.getEncoder().encodeToString(new byte[32]));
        service=newService();service.bootstrap();
    }

    ModelConfigurationService newService(){return newService(jdbc);}
    ModelConfigurationService newService(JdbcTemplate template){
        var beans=new StaticListableBeanFactory(Map.of("memory",memory));
        var result=new ModelConfigurationService(template,new DataSourceTransactionManager(template.getDataSource()),users,audit,json,props,agent,beans.getBeanProvider(MemoryModelConfigApi.class),keyFile.toString(),"qwen-plus");
        result.setJsonProbe(probe);return result;
    }
    ModelConfigurationService.Document doc(){return service.get(boss,service.active().version()).document();}
    ModelConfigurationService.Document withDefault(String id){var d=doc();return new ModelConfigurationService.Document(d.models(),id,d.fallbackModels(),d.fallbackEnabled(),d.timeoutMs(),d.firstTokenTimeoutMs(),d.maxOutputTokens(),d.memoryModel());}
    ModelConfigurationService.View draft(String request,Map<String,String> keys){return service.draft(boss,new ModelConfigurationService.Draft(service.active().version(),request,doc(),keys));}
    void compatible(long revision,String request){when(probe.check(any(),anyString())).thenReturn(true);assertThat(service.probeJson(boss,revision,"dashscope:qwen-plus",request).status()).isEqualTo("PASSED");}
    void publish(long revision,String request){service.validate(boss,revision,"validate-"+request);when(memory.appliedRevision()).thenReturn(revision);service.publish(boss,revision,"publish-"+request);}

    @Test void bootstrapKeepsDeployedDefaultAndOrderAndNeverReturnsCredentials() throws Exception {
        assertThat(service.active().defaultModel()).isEqualTo(agent.getModel());
        assertThat(doc().fallbackModels()).containsExactly("dashscope:glm-fixture");
        assertThat(json.writeValueAsString(service.list(boss))).doesNotContain("fixture-old-key","sealed_snapshot","apiKey","baseUrl","master.key");
        assertThat(jdbc.queryForObject("SELECT sealed_snapshot FROM llm_configuration WHERE revision=1",String.class)).doesNotContain("fixture-old-key");
        newService().bootstrap();assertThat(service.active().version()).isEqualTo(1);
    }
    @Test void bootstrapDoesNotDropDefaultFromExplicitBackupOrder() throws Exception {
        com.ruanzhu.doorhandle.module.ai.testsupport.CompactModelConfigurationFixture.install(jdbc);
        props.setFallbackModels(List.of("dashscope:qwen-plus","dashscope:glm-fixture"));newService().bootstrap();
        assertThat(doc().fallbackModels()).containsExactly("dashscope:qwen-plus","dashscope:glm-fixture");
    }
    @Test void existingEncryptedHistoryCannotBeBootstrappedWithoutItsControlRecord() throws Exception {
        String original=jdbc.queryForObject("SELECT sealed_snapshot FROM llm_configuration WHERE revision=1",String.class);
        // Simulate an incomplete restore in this already admitted disposable database.
        // Dropping the fixture table is deliberate: the production DELETE trigger must block a reset.
        jdbc.execute("DROP TABLE runtime_state");
        com.ruanzhu.doorhandle.module.ai.testsupport.CompactCoordinationFixture.install(jdbc);
        assertThatThrownBy(()->newService().bootstrap()).hasMessageContaining("禁止重新初始化");
        assertThat(jdbc.queryForObject("SELECT sealed_snapshot FROM llm_configuration WHERE revision=1",String.class)).isEqualTo(original);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_configuration",Long.class)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM runtime_state WHERE namespace='MODEL_CONFIG_CONTROL'",Long.class)).isZero();
    }
    @Test void restoredDatabaseRequiresItsOriginalEncryptionKey() throws Exception {
        String original=jdbc.queryForObject("SELECT sealed_snapshot FROM llm_configuration WHERE revision=1",String.class);
        byte[] replacement=new byte[32];Arrays.fill(replacement,(byte)7);
        Files.writeString(keyFile,Base64.getEncoder().encodeToString(replacement));
        assertThatThrownBy(()->newService().bootstrap()).hasMessageContaining("不能安全加载");
        assertThat(jdbc.queryForObject("SELECT sealed_snapshot FROM llm_configuration WHERE revision=1",String.class)).isEqualTo(original);
        assertThat(jdbc.queryForObject("SELECT counter_value FROM runtime_state WHERE namespace='MODEL_CONFIG_CONTROL'",Long.class)).isEqualTo(1);
    }
    @Test void conflictingPublishedHistoryCannotBeSilentlyAcceptedAtStartup() {
        var candidate=draft("inconsistent-published",Map.of());
        jdbc.update("UPDATE llm_configuration SET status='PUBLISHED' WHERE revision=?",candidate.revision());
        assertThatThrownBy(()->newService().bootstrap()).hasMessageContaining("禁止重新初始化");
        assertThat(jdbc.queryForObject("SELECT current_ref FROM runtime_state WHERE namespace='MODEL_CONFIG_CONTROL'",String.class)).isEqualTo("1");
    }
    @Test void concurrentMysqlProbeRequestsCannotRepeatThePaidExternalCheck() throws Exception {
        Assumptions.assumeTrue(System.getProperty("agent.model-config.mysql-file")!=null,
                "The stale-snapshot regression requires an admitted ECS MySQL fixture");
        var candidate=draft("concurrent-probe",Map.of());
        var firstHoldingLock=new CountDownLatch(1);
        var contenderAtLock=new CountDownLatch(1);
        var firstAudit=new java.util.concurrent.atomic.AtomicBoolean(true);
        doAnswer(invocation->{
            if(firstAudit.compareAndSet(true,false)) {
                firstHoldingLock.countDown();
                assertThat(contenderAtLock.await(10,TimeUnit.SECONDS)).isTrue();
            }
            return null;
        }).when(audit).append(any());
        var contenderJdbc=new JdbcTemplate(jdbc.getDataSource()) {
            @Override public List<Map<String,Object>> queryForList(String sql,Object... arguments) {
                if(sql.contains("SELECT current_ref,counter_value")&&sql.contains("FOR UPDATE"))contenderAtLock.countDown();
                return super.queryForList(sql,arguments);
            }
        };
        var contender=newService(contenderJdbc);
        when(probe.check(any(),anyString())).thenReturn(true);
        var executor=Executors.newFixedThreadPool(2);
        try {
            var first=executor.submit(()->service.probeJson(boss,candidate.revision(),"dashscope:qwen-plus","same-paid-probe"));
            assertThat(firstHoldingLock.await(10,TimeUnit.SECONDS)).isTrue();
            var second=executor.submit(()->contender.probeJson(boss,candidate.revision(),"dashscope:qwen-plus","same-paid-probe"));
            assertThat(first.get(15,TimeUnit.SECONDS).status()).isEqualTo("PASSED");
            assertThat(second.get(15,TimeUnit.SECONDS).status()).isIn("STARTED","PASSED");
            verify(probe,times(1)).check(any(),anyString());
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='MODEL_JSON_PROBE' AND request_id='same-paid-probe'",Long.class)).isEqualTo(1);
        } finally {contenderAtLock.countDown();executor.shutdownNow();}
    }
    @Test void mysqlProtectsPermanentRevocationsAndConfigurationControl() {
        Assumptions.assumeTrue(System.getProperty("agent.model-config.mysql-file")!=null,
                "MySQL triggers require the admitted ECS fixture; H2 cannot prove them");
        doThrow(new IllegalStateException("bridge unavailable")).when(memory).revokeCredential(anyString());
        service.revoke(boss,"dashscope",1,"guard-revoke");
        assertThatThrownBy(()->jdbc.update("DELETE FROM runtime_state WHERE namespace='MODEL_KEY_REVOCATION'"))
                .isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThatThrownBy(()->jdbc.update("UPDATE runtime_state SET namespace='OTHER' WHERE namespace='MODEL_KEY_REVOCATION'"))
                .isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThatThrownBy(()->jdbc.update("DELETE FROM runtime_state WHERE namespace='MODEL_CONFIG_CONTROL'"))
                .isInstanceOf(org.springframework.dao.DataAccessException.class);
        doNothing().when(memory).revokeCredential(anyString());
        service.reconcileMemory();
        assertThat(jdbc.queryForObject("SELECT counter_value FROM runtime_state WHERE namespace='MODEL_KEY_REVOCATION'",Long.class)).isEqualTo(1);
        assertThatThrownBy(()->jdbc.update("UPDATE runtime_state SET counter_value=0 WHERE namespace='MODEL_KEY_REVOCATION'"))
                .isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThatThrownBy(()->jdbc.update("UPDATE runtime_state SET current_ref='0',counter_value=0 WHERE namespace='MODEL_CONFIG_CONTROL'"))
                .isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThatThrownBy(()->service.assertUsable(1,"dashscope:qwen-plus")).hasMessageContaining("不可用");
    }
    @Test void permissionsAreRefreshedAndForgedSupervisorRoleIsRejected(){
        assertThatThrownBy(()->service.list(new AgentActor(4,"worker",AgentActor.Role.SUPERVISOR))).isInstanceOf(SecurityException.class);
        var candidate=draft("draft-auth",Map.of());
        when(users.current(3,"boss")).thenReturn(new BusinessUserDirectory.Identity(3,"boss",false));
        assertThatThrownBy(()->service.publish(boss,candidate.revision(),"publish-auth")).isInstanceOf(SecurityException.class);
        verifyNoInteractions(memory);
    }
    @Test void repeatedDraftIsDeduplicatedButChangedPayloadUnderSameRequestIsRejected(){
        var first=draft("same-draft",Map.of());assertThat(draft("same-draft",Map.of()).revision()).isEqualTo(first.revision());
        assertThatThrownBy(()->service.draft(boss,new ModelConfigurationService.Draft(1,"same-draft",doc(),Map.of("dashscope","different"))))
                .hasMessageContaining("请求编号");
    }
    @Test void auditFailureRollsBackDraftAndRevisionCounter(){
        doThrow(new IllegalStateException("audit unavailable")).when(audit).append(any());
        assertThatThrownBy(()->draft("audit-failed",Map.of())).hasMessage("audit unavailable");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_configuration",Long.class)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT counter_value FROM runtime_state WHERE namespace='MODEL_CONFIG_CONTROL' AND owner_id=0 AND scope_key='GLOBAL'",Long.class)).isEqualTo(1);
    }
    @Test void retiredTaskSnapshotsKeepOldKeysWhileNewTasksSeeNewConfiguration(){
        var original=service.active();var candidate=draft("rotate",Map.of("dashscope","fixture-new-key"));
        assertThatThrownBy(()->service.validate(boss,candidate.revision(),"not-probed")).hasMessageContaining("JSON");
        compatible(candidate.revision(),"probe-rotation");publish(candidate.revision(),"rotation");
        service.assertUsable(original.version(),original.defaultModel());
        assertThat(service.runtime(original.version()).properties().getDashscope().getApiKey()).isEqualTo("fixture-old-key");
        assertThat(service.runtime(service.active().version()).properties().getDashscope().getApiKey()).isEqualTo("fixture-new-key");
        assertThat(service.get(boss,candidate.revision()).memoryState()).isEqualTo("APPLIED");
    }
    @Test void oldRevokeRetryCannotRevokeTheReplacementKey(){
        service.revoke(boss,"dashscope",1,"revoke-original");
        assertThatThrownBy(()->service.assertUsable(1,"dashscope:qwen-plus")).hasMessageContaining("不可用");
        var replacement=draft("replacement",Map.of("dashscope","fixture-new-key"));compatible(replacement.revision(),"probe-new");publish(replacement.revision(),"replacement");
        service.revoke(boss,"dashscope",1,"revoke-original");
        service.assertUsable(replacement.revision(),"dashscope:qwen-plus");
        assertThatThrownBy(()->service.revoke(boss,"dashscope",1,"stale-revoke")).hasMessageContaining("生效版本已变化");
    }
    @Test void staleDraftAndConcurrentPublishCannotReplaceEachOther() throws Exception {
        var a=draft("parallel-a",Map.of());var b=draft("parallel-b",Map.of());service.validate(boss,a.revision(),"validate-a");service.validate(boss,b.revision(),"validate-b");
        var gate=new CountDownLatch(1);var executor=Executors.newFixedThreadPool(2);
        try{
            var futures=List.of(a,b).stream().map(candidate->executor.submit(()->{gate.await();try{service.publish(boss,candidate.revision(),"publish-"+candidate.revision());return true;}catch(org.springframework.web.server.ResponseStatusException expected){assertThat(expected.getStatusCode().value()).isEqualTo(409);return false;}})).toList();
            gate.countDown();int successes=0;for(var future:futures)if(future.get(5,TimeUnit.SECONDS))successes++;assertThat(successes).isEqualTo(1);
        }finally{executor.shutdownNow();}
        var winner=service.active().version();var loser=winner==a.revision()?b.revision():a.revision();
        assertThatThrownBy(()->service.validate(boss,loser,"stale-validate")).hasMessageContaining("生效版本已变化");
        service.publish(boss,winner,"publish-"+winner);assertThat(service.active().version()).isEqualTo(winner);
    }
    @Test void pendingMemoryApplicationSurvivesRestartAndNeverRunsExtraction(){
        var candidate=draft("pending",Map.of());service.validate(boss,candidate.revision(),"pending-validate");
        doThrow(new IllegalStateException()).when(memory).apply(anyLong());service.publish(boss,candidate.revision(),"pending-publish");
        assertThat(service.get(boss,candidate.revision()).memoryState()).isEqualTo("PENDING");
        assertThatThrownBy(service::assertMemoryAvailable).hasMessageContaining("不会开始提炼");
        var restarted=newService();restarted.bootstrap();doNothing().when(memory).apply(anyLong());when(memory.appliedRevision()).thenReturn(candidate.revision());restarted.reconcileMemory();
        assertThat(restarted.get(boss,candidate.revision()).memoryState()).isEqualTo("APPLIED");
        restarted.assertMemoryAvailable();
        verifyNoInteractions(probe);
    }
    @Test void revocationImmediatelyBlocksNewExtractionEvenWhenBridgeIsUnavailable(){
        service.assertMemoryAvailable();
        doThrow(new IllegalStateException("bridge unavailable")).when(memory).revokeCredential(anyString());
        service.revoke(boss,"dashscope",1,"revoke-extraction");
        assertThatThrownBy(service::assertMemoryAvailable).hasMessageContaining("凭证已撤销");
        assertThat(jdbc.queryForObject("SELECT counter_value FROM runtime_state WHERE namespace='MODEL_KEY_REVOCATION'",Boolean.class)).isFalse();
        doNothing().when(memory).revokeCredential(anyString());newService().reconcileMemory();
        assertThat(jdbc.queryForObject("SELECT counter_value FROM runtime_state WHERE namespace='MODEL_KEY_REVOCATION'",Boolean.class)).isTrue();
    }
    @Test void jsonProbeReceiptPreventsPaidReplayAndUnknownAttemptStaysUnknown(){
        var candidate=draft("probe-draft",Map.of("dashscope","fixture-new-key"));compatible(candidate.revision(),"probe-once");
        service.probeJson(boss,candidate.revision(),"dashscope:qwen-plus","probe-once");verify(probe,times(1)).check(any(),anyString());
        when(probe.check(any(),anyString())).thenThrow(new IllegalStateException("external result unknown"));
        assertThatThrownBy(()->service.probeJson(boss,candidate.revision(),"dashscope:qwen-plus","lost-result"))
                .hasMessage("external result unknown");
        var restarted=newService();restarted.bootstrap();
        assertThat(restarted.probeJson(boss,candidate.revision(),"dashscope:qwen-plus","lost-result").status()).isEqualTo("STARTED");
        verify(probe,times(2)).check(any(),anyString());
        assertThatThrownBy(()->service.probeJson(boss,candidate.revision(),"dashscope:glm-fixture","probe-once")).hasMessageContaining("其他模型");
    }
    @Test void restoreCreatesReviewableDraftAndKeepsCurrentKeys(){
        var candidate=draft("rotation-for-restore",Map.of("dashscope","fixture-new-key"));compatible(candidate.revision(),"probe-restore");publish(candidate.revision(),"for-restore");
        var restored=service.restore(boss,1,candidate.revision(),"restore-original");
        assertThat(restored.status()).isEqualTo("DRAFT");assertThat(service.active().version()).isEqualTo(candidate.revision());
        assertThat(service.runtime(restored.revision()).properties().getDashscope().getApiKey()).isEqualTo("fixture-new-key");
    }
}
