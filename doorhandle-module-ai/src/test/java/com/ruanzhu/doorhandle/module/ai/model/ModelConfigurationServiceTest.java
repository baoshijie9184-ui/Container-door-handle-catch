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
        if(mysql){
            var config=json.readTree(Files.readString(Path.of(System.getProperty("agent.model-config.mysql-file"))));
            String database=config.path("database").asText(),url=config.path("url").asText();
            if(!database.matches("doorhandle_model_verify_[a-f0-9]{10}")||!url.startsWith("jdbc:mysql://127.0.0.1:3306/"+database+"?"))throw new SecurityException("Only an isolated local model verification database is allowed");
            dataSource=new DriverManagerDataSource(url,config.path("username").asText(),config.path("password").asText());
        }
        jdbc=new JdbcTemplate(dataSource);
        String sql=new String(Objects.requireNonNull(getClass().getResourceAsStream("/db/migration-V41-model-configuration.sql")).readAllBytes(),java.nio.charset.StandardCharsets.UTF_8);
        // Same table/column/unique definitions; H2 cannot accept MySQL secondary-key clauses.
        if(mysql){for(String table:List.of("agent_model_config_command","agent_model_json_probe","agent_model_revoked_key","agent_model_configuration","agent_model_config_control"))jdbc.execute("DROP TABLE IF EXISTS "+table);}
        else sql=sql.replaceAll("(?m)^ KEY idx[^\\n]*\\n","").replaceAll(",\\s*\\)",")")
                .replaceAll("ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin","");
        try(var connection=dataSource.getConnection()){
            org.springframework.jdbc.datasource.init.ScriptUtils.executeSqlScript(connection,new org.springframework.core.io.ByteArrayResource(sql.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
        }
        users=mock(BusinessUserDirectory.class);
        when(users.current(3,"boss")).thenReturn(new BusinessUserDirectory.Identity(3,"boss",true));
        when(users.current(4,"worker")).thenReturn(new BusinessUserDirectory.Identity(4,"worker",false));
        audit=mock(OperationsAuditApi.class);memory=mock(MemoryModelConfigApi.class);probe=mock(ModelJsonCompatibilityProbe.class);
        props=new AgentModelProperties();props.getDashscope().setApiKey("fixture-old-key");props.setFallbackEnabled(true);props.setFallbackModels(List.of("dashscope:glm-fixture"));props.getDashscope().setAdditionalModels(List.of("glm-fixture"));
        agent=new AgentScopeProperties();agent.setModel("dashscope:qwen-plus");
        keyFile=directory.resolve("master.key");Files.writeString(keyFile,Base64.getEncoder().encodeToString(new byte[32]));
        service=newService();service.bootstrap();
    }

    ModelConfigurationService newService(){
        var beans=new StaticListableBeanFactory(Map.of("memory",memory));
        var result=new ModelConfigurationService(jdbc,new DataSourceTransactionManager(jdbc.getDataSource()),users,audit,json,props,agent,beans.getBeanProvider(MemoryModelConfigApi.class),keyFile.toString(),"qwen-plus");
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
        assertThat(jdbc.queryForObject("SELECT sealed_snapshot FROM agent_model_configuration WHERE revision=1",String.class)).doesNotContain("fixture-old-key");
        newService().bootstrap();assertThat(service.active().version()).isEqualTo(1);
    }
    @Test void bootstrapDoesNotDropDefaultFromExplicitBackupOrder(){
        jdbc.update("DELETE FROM agent_model_configuration");jdbc.update("UPDATE agent_model_config_control SET active_revision=0,sequence_value=0");
        props.setFallbackModels(List.of("dashscope:qwen-plus","dashscope:glm-fixture"));newService().bootstrap();
        assertThat(doc().fallbackModels()).containsExactly("dashscope:qwen-plus","dashscope:glm-fixture");
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
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_model_configuration",Long.class)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT sequence_value FROM agent_model_config_control",Long.class)).isEqualTo(1);
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
        assertThat(jdbc.queryForObject("SELECT memory_propagated FROM agent_model_revoked_key",Boolean.class)).isFalse();
        doNothing().when(memory).revokeCredential(anyString());newService().reconcileMemory();
        assertThat(jdbc.queryForObject("SELECT memory_propagated FROM agent_model_revoked_key",Boolean.class)).isTrue();
    }
    @Test void jsonProbeReceiptPreventsPaidReplayAndUnknownAttemptStaysUnknown(){
        var candidate=draft("probe-draft",Map.of("dashscope","fixture-new-key"));compatible(candidate.revision(),"probe-once");
        service.probeJson(boss,candidate.revision(),"dashscope:qwen-plus","probe-once");verify(probe,times(1)).check(any(),anyString());
        jdbc.update("INSERT INTO agent_model_json_probe(revision,model_id,request_id,status,created_at) VALUES(?,?,?,'STARTED',CURRENT_TIMESTAMP)",candidate.revision(),"dashscope:qwen-plus","lost-result");
        assertThat(service.probeJson(boss,candidate.revision(),"dashscope:qwen-plus","lost-result").status()).isEqualTo("STARTED");verify(probe,times(1)).check(any(),anyString());
        assertThatThrownBy(()->service.probeJson(boss,candidate.revision(),"dashscope:glm-fixture","probe-once")).hasMessageContaining("其他模型");
    }
    @Test void restoreCreatesReviewableDraftAndKeepsCurrentKeys(){
        var candidate=draft("rotation-for-restore",Map.of("dashscope","fixture-new-key"));compatible(candidate.revision(),"probe-restore");publish(candidate.revision(),"for-restore");
        var restored=service.restore(boss,1,candidate.revision(),"restore-original");
        assertThat(restored.status()).isEqualTo("DRAFT");assertThat(service.active().version()).isEqualTo(candidate.revision());
        assertThat(service.runtime(restored.revision()).properties().getDashscope().getApiKey()).isEqualTo("fixture-new-key");
    }
}
