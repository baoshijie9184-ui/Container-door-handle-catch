package com.ruanzhu.doorhandle.module.model.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.extension.spring.MybatisSqlSessionFactoryBean;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.OperationsAuditApi;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.model.controller.ModelController;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.module.model.mapper.ModelInfoMapper;
import com.ruanzhu.doorhandle.module.model.service.impl.ModelServiceImpl;
import com.ruanzhu.doorhandle.module.model.testsupport.ModelFileMigrationFixture;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import com.ruanzhu.doorhandle.module.system.service.BusinessMutationAudit;
import com.ruanzhu.doorhandle.module.system.service.OperationsAuditService;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.api.io.TempDir;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.context.annotation.*;
import org.springframework.core.env.MapPropertySource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.*;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import org.springframework.transaction.support.TransactionTemplate;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;

/** Actual admitted ECS MySQL, managed bytes, HTTP retry, Spring proxy and BUSINESS_COMMAND receipts together. */
@EnabledIfSystemProperty(named="model.file.copy.source-config",matches=".+")
@EnabledIfSystemProperty(named="model.file.copy.target-config",matches=".+")
class ModelUploadIdempotencyMySqlTest {
    static ModelFileMigrationFixture fixture;
    static BusinessUserDirectory users;
    static Path uploads;
    static final AtomicBoolean rejectAudit=new AtomicBoolean(),loseResponse=new AtomicBoolean();
    @TempDir Path directory;
    AnnotationConfigApplicationContext context;JdbcTemplate jdbc;MockMvc http;
    final ObjectMapper json=new ObjectMapper();
    static final byte[] BODY={1,2,3,4,5,6};
    @Configuration @EnableAspectJAutoProxy(proxyTargetClass=true) @EnableTransactionManagement
    static class Config {
        @Bean JdbcTemplate jdbc(){return fixture.target();}
        @Bean PlatformTransactionManager manager(JdbcTemplate jdbc){return new DataSourceTransactionManager(jdbc.getDataSource());}
        @Bean ModelInfoMapper models()throws Exception{
            var config=new MybatisConfiguration();config.setMapUnderscoreToCamelCase(true);config.addMapper(ModelInfoMapper.class);
            var factory=new MybatisSqlSessionFactoryBean();factory.setDataSource(fixture.targetDataSource());factory.setConfiguration(config);
            factory.setMapperLocations(new ClassPathResource("mapper/ModelInfoMapper.xml"));return new SqlSessionTemplate(factory.getObject()).getMapper(ModelInfoMapper.class);
        }
        @Bean ModelMutationIdentity identity(){return new ModelMutationIdentity(users);}
        @Bean ModelFilePersistence files(JdbcTemplate jdbc){return new ModelFilePersistence(jdbc,new ObjectMapper());}
        @Bean OperationsAuditApi audit(JdbcTemplate jdbc){
            var delegate=new OperationsAuditService(jdbc,users);
            return new OperationsAuditApi(){public void append(Event event){delegate.append(event);}public void appendChange(ChangeEvent event){if(rejectAudit.get())throw new IllegalStateException("audit unavailable");delegate.appendChange(event);}};
        }
        @Bean ModelMutationParticipant participant(JdbcTemplate jdbc){return new ModelMutationParticipant(jdbc,users);}
        @Bean BusinessMutationAudit aspect(OperationsAuditApi audit,PlatformTransactionManager manager){return new BusinessMutationAudit(audit,users,manager);}
        @Bean ModelFileJournal journal(ModelFilePersistence files,PlatformTransactionManager manager,OperationsAuditApi audit,ModelMutationIdentity identity){return new ModelFileJournal(files,manager,audit,identity);}
        @Bean ModelUploadFiles uploads(org.springframework.beans.factory.ObjectProvider<ModelFileJournal> journals,ModelMutationIdentity identity){return new ModelUploadFiles(journals,identity,uploads.toString(),10000);}
        @Bean ModelOperationAuditStore logs(JdbcTemplate jdbc){return new ModelOperationAuditStore(jdbc,new ObjectMapper());}
        @Bean ModelValidationService validation(){var validation=mock(ModelValidationService.class);when(validation.validate(any())).thenReturn(new ModelValidationService.ValidationResult("PASSED","scripted fixture"));return validation;}
        @Bean ModelRegistrationService registration(ModelInfoMapper models,ModelOperationAuditStore logs,ModelMutationIdentity identity,org.springframework.beans.factory.ObjectProvider<ModelFileJournal> journals){return new ModelRegistrationService(models,logs,identity,journals);}
        @Bean ModelServiceImpl service(ModelInfoMapper models,ModelOperationAuditStore logs,ModelValidationService validation,ModelUploadFiles files,ModelRegistrationService registration,org.springframework.beans.factory.ObjectProvider<ModelFileJournal> journals,ModelMutationIdentity identity){
            var service=new ModelServiceImpl(models,logs,validation,files,registration,journals,identity);ReflectionTestUtils.setField(service,"maxUploadBytes",10000L);return service;
        }
    }
    @BeforeEach void setup()throws Exception{
        fixture=new ModelFileMigrationFixture();jdbc=fixture.target();uploads=directory.resolve("managed");rejectAudit.set(false);loseResponse.set(false);
        jdbc.update("INSERT INTO users(id,username,password,role) VALUES(77,'supervisor-77','fixture','SUPERVISOR')");
        users=mock(BusinessUserDirectory.class);var identity=new BusinessUserDirectory.Identity(77,"supervisor-77",true);
        when(users.authenticated()).thenReturn(identity);when(users.current(77,"supervisor-77")).thenReturn(identity);
        when(users.lockCurrent(77,"supervisor-77")).thenAnswer(call->{jdbc.queryForList("SELECT id FROM users WHERE id=77 FOR UPDATE");return identity;});
        context=new AnnotationConfigApplicationContext();context.getEnvironment().getPropertySources().addFirst(new MapPropertySource("upload-test",Map.of("operations.audit.enabled","true","collaboration.mutations.enabled","true","model.file-journal.enabled","true")));
        context.register(Config.class);context.refresh();
        var actual=context.getBean(ModelServiceImpl.class);ModelService entry=mock(ModelService.class);
        when(entry.uploadModel(any(),anyString(),anyString(),any())).thenAnswer(call->{
            var result=actual.uploadModel(call.getArgument(0),call.getArgument(1),call.getArgument(2),call.getArgument(3));
            if(loseResponse.getAndSet(false))throw new org.springframework.dao.DataAccessResourceFailureException("response lost after commit");return result;
        });
        var controller=new ModelController(entry,context.getBeanProvider(ModelFileJournal.class));ReflectionTestUtils.setField(controller,"mutationProtectionEnabled",true);
        http=MockMvcBuilders.standaloneSetup(controller).setControllerAdvice(new com.ruanzhu.doorhandle.common.GlobalExceptionHandler(),new com.ruanzhu.doorhandle.module.system.controller.ResultHttpStatusAdvice()).build();authenticate();
    }
    @AfterEach void cleanup()throws Exception{SecurityContextHolder.clearContext();if(context!=null)context.close();if(fixture!=null)fixture.close();}
    static void authenticate(){var principal=new TenantPrincipal(77L,"supervisor-77","",List.of());SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken(principal,null,List.of()));}
    MvcResult upload(String request,byte[] bytes,String description)throws Exception{
        return http.perform(multipart("/api/models/upload").file(new MockMultipartFile("file","model.onnx","application/octet-stream",bytes))
                .param("modelName","managed-model").param("version","v1").param("updateDescription",description).header("X-Request-ID",request)).andReturn();
    }
    int count(String table){return jdbc.queryForObject("SELECT COUNT(*) FROM "+table,Integer.class);}
    long fileCount()throws Exception{if(!Files.exists(uploads))return 0;try(var files=Files.list(uploads)){return files.count();}}
    String state(){return jdbc.queryForObject("SELECT status FROM workflow_instance WHERE kind='MODEL_FILE_UPLOAD'",String.class);}
    String modelId(MvcResult response)throws Exception{return json.readTree(response.getResponse().getContentAsString()).path("data").path("modelId").asText();}
    @Test void responseLossRetryReturnsOriginalModelAndAuditReceiptWithoutAnotherFileOrValidation()throws Exception{
        loseResponse.set(true);assertThat(upload("lost-response",BODY,"original").getResponse().getStatus()).isEqualTo(500);
        String audit=jdbc.queryForObject("SELECT id FROM audit_event WHERE kind='OPERATIONS' AND payload_version=2 AND action='UPLOAD'",String.class);
        var replay=upload("lost-response",BODY,"original");assertThat(replay.getResponse().getStatus()).isEqualTo(200);
        assertThat(modelId(replay)).isEqualTo(jdbc.queryForObject("SELECT model_id FROM model_management",String.class));
        assertThat(replay.getResponse().getHeader("X-Audit-ID")).isEqualTo(audit);assertThat(replay.getResponse().getHeader("X-Resource-Version")).isNotBlank();
        assertThat(count("model_management")).isEqualTo(1);assertThat(fileCount()).isEqualTo(1);assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='BUSINESS_COMMAND'",Integer.class)).isEqualTo(1);
        verify(context.getBean(ModelValidationService.class),times(1)).validate(any());
    }
    @Test void sameRequestDifferentFileBytesOrMetadataIsHttp409WithoutExtraFiles()throws Exception{
        assertThat(upload("content-conflict",BODY,"original").getResponse().getStatus()).isEqualTo(200);
        assertThat(upload("content-conflict",new byte[]{9,9},"original").getResponse().getStatus()).isEqualTo(409);
        assertThat(upload("content-conflict",BODY,"changed description").getResponse().getStatus()).isEqualTo(409);
        assertThat(fileCount()).isEqualTo(1);assertThat(count("model_management")).isEqualTo(1);assertThat(state()).isEqualTo("REGISTERED");verify(context.getBean(ModelValidationService.class),times(1)).validate(any());
    }
    @Test void knownRegistrationRollbackCanUseTheSameReadyFileOnAnExplicitRetry()throws Exception{
        rejectAudit.set(true);assertThat(upload("audit-rollback",BODY,"original").getResponse().getStatus()).isEqualTo(500);
        assertThat(state()).isEqualTo("FILE_READY");assertThat(count("model_management")).isZero();assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='BUSINESS_COMMAND'",Integer.class)).isZero();
        String file=jdbc.queryForObject("SELECT resource_id FROM workflow_instance WHERE kind='MODEL_FILE_UPLOAD'",String.class);
        rejectAudit.set(false);assertThat(upload("audit-rollback",BODY,"original").getResponse().getStatus()).isEqualTo(200);
        assertThat(jdbc.queryForObject("SELECT resource_id FROM workflow_instance WHERE kind='MODEL_FILE_UPLOAD'",String.class)).isEqualTo(file);assertThat(fileCount()).isEqualTo(1);
    }
    @Test void uncertainReservationNeverCreatesAnotherFile()throws Exception{
        String request="reserved-unknown",id=UUID.randomUUID().toString(),hash=java.util.HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(BODY));
        var tx=new TransactionTemplate(context.getBean(PlatformTransactionManager.class));
        tx.executeWithoutResult(status->context.getBean(ModelFilePersistence.class).claim(77,id,request,uploads.resolve(id+".onnx").toString(),ModelFileProtocol.uploadIntentDigest(77,request,hash,BODY.length,"managed-model","v1","original")));
        assertThat(upload(request,BODY,"original").getResponse().getStatus()).isEqualTo(409);assertThat(state()).isEqualTo("RESERVED");assertThat(fileCount()).isZero();assertThat(count("model_management")).isZero();verifyNoInteractions(context.getBean(ModelValidationService.class));
    }
    @Test void registeredFileWithMissingBusinessReceiptFailsClosedInsteadOfReexecuting()throws Exception{
        // A pre-command registration is valid history; completed command receipts must never be deleted.
        var aspect=context.getBean(BusinessMutationAudit.class);ReflectionTestUtils.setField(aspect,"mutationProtectionEnabled",false);
        try{assertThat(upload("missing-receipt",BODY,"original").getResponse().getStatus()).isEqualTo(200);}
        finally{ReflectionTestUtils.setField(aspect,"mutationProtectionEnabled",true);}
        assertThat(state()).isEqualTo("REGISTERED");assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='BUSINESS_COMMAND'",Integer.class)).isZero();
        var originalModel=jdbc.queryForList("SELECT * FROM model_management ORDER BY model_id");
        var originalFiles=jdbc.queryForList("SELECT * FROM workflow_instance WHERE kind='MODEL_FILE_UPLOAD' ORDER BY workflow_id");
        var originalAudit=jdbc.queryForList("SELECT * FROM audit_event ORDER BY id");
        var retry=upload("missing-receipt",BODY,"original");assertThat(retry.getResponse().getStatus()).isEqualTo(409);
        assertThat(retry.getResponse().getHeader("X-Audit-ID")).isNull();assertThat(retry.getResponse().getHeader("X-Resource-Version")).isNull();
        assertThat(fileCount()).isEqualTo(1);assertThat(count("model_management")).isEqualTo(1);
        assertThat(jdbc.queryForList("SELECT * FROM model_management ORDER BY model_id")).isEqualTo(originalModel);
        assertThat(jdbc.queryForList("SELECT * FROM workflow_instance WHERE kind='MODEL_FILE_UPLOAD' ORDER BY workflow_id")).isEqualTo(originalFiles);
        assertThat(jdbc.queryForList("SELECT * FROM audit_event ORDER BY id")).isEqualTo(originalAudit);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='BUSINESS_COMMAND'",Integer.class)).isZero();verify(context.getBean(ModelValidationService.class),times(1)).validate(any());
    }
    @Test void changedManagedBytesAreNotRewrittenOrRevalidated()throws Exception{
        assertThat(upload("changed-managed",BODY,"original").getResponse().getStatus()).isEqualTo(200);
        Path file;try(var files=Files.list(uploads)){file=files.findFirst().orElseThrow();}Files.write(file,new byte[]{8,8,8});
        assertThat(upload("changed-managed",BODY,"original").getResponse().getStatus()).isEqualTo(409);assertThat(Files.readAllBytes(file)).containsExactly(new byte[]{8,8,8});assertThat(fileCount()).isEqualTo(1);verify(context.getBean(ModelValidationService.class),times(1)).validate(any());
    }
    @Test void retainedModelCannotBeResurrectedByReplayingItsUpload()throws Exception{
        var result=upload("retained-upload",BODY,"original");assertThat(result.getResponse().getStatus()).isEqualTo(200);
        var model=context.getBean(ModelInfoMapper.class).selectByModelId(Integer.valueOf(modelId(result)));
        new TransactionTemplate(context.getBean(PlatformTransactionManager.class)).executeWithoutResult(status->{
            context.getBean(ModelFileJournal.class).retain(model);jdbc.update("DELETE FROM model_management WHERE model_id=?",model.getModelId());
        });
        assertThat(upload("retained-upload",BODY,"original").getResponse().getStatus()).isEqualTo(409);assertThat(state()).isEqualTo("RETAINED");assertThat(count("model_management")).isZero();assertThat(fileCount()).isEqualTo(1);
        verify(context.getBean(ModelValidationService.class),times(1)).validate(any());
    }
    @Test void historicalPathOnlyRequestDigestCannotBeGuessedIntoAReplayableIntent()throws Exception{
        String id=UUID.randomUUID().toString();Path file=uploads.resolve(id+".onnx");Files.createDirectories(uploads);Files.write(file,BODY);
        var journal=context.getBean(ModelFileJournal.class);journal.reserve(id,"legacy-request",file.toString());
        String hash=java.util.HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(BODY));
        journal.ready(new ModelUploadFiles.Prepared(id,"legacy-request",77,file,hash,BODY.length));
        assertThat(upload("legacy-request",BODY,"original").getResponse().getStatus()).isEqualTo(409);assertThat(state()).isEqualTo("FILE_READY");assertThat(fileCount()).isEqualTo(1);assertThat(count("model_management")).isZero();verifyNoInteractions(context.getBean(ModelValidationService.class));
    }
    @Test void concurrentIdenticalHttpRequestsHaveOneFileAndOneBusinessMutation()throws Exception{
        var start=new CountDownLatch(1);var pool=Executors.newFixedThreadPool(2);
        try{var calls=new ArrayList<Future<Integer>>();for(int n=0;n<2;n++)calls.add(pool.submit(()->{authenticate();try{if(!start.await(5,TimeUnit.SECONDS))throw new IllegalStateException("barrier");return upload("concurrent-upload",BODY,"original").getResponse().getStatus();}finally{SecurityContextHolder.clearContext();}}));
            start.countDown();var codes=List.of(calls.get(0).get(20,TimeUnit.SECONDS),calls.get(1).get(20,TimeUnit.SECONDS));assertThat(codes).contains(200).allMatch(code->code==200||code==409);
        }finally{start.countDown();pool.shutdownNow();assertThat(pool.awaitTermination(5,TimeUnit.SECONDS)).isTrue();}
        assertThat(upload("concurrent-upload",BODY,"original").getResponse().getStatus()).isEqualTo(200);assertThat(fileCount()).isEqualTo(1);assertThat(count("model_management")).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='OPERATIONS' AND payload_version=2 AND action='UPLOAD'",Integer.class)).isEqualTo(1);
    }
}
