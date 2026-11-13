package com.ruanzhu.doorhandle.module.detection.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.extension.spring.MybatisSqlSessionFactoryBean;
import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.collaboration.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.detection.service.impl.DetectionTaskServiceImpl;
import com.ruanzhu.doorhandle.module.detection.support.ReportMySqlFixture;
import com.ruanzhu.doorhandle.contracts.detection.DetectionTaskFinishedEvent;
import com.ruanzhu.doorhandle.module.system.service.OperationsAuditService;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.context.annotation.*;
import org.springframework.core.env.MapPropertySource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import org.springframework.transaction.event.TransactionalEventListener;
import javax.sql.DataSource;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import static com.ruanzhu.doorhandle.module.detection.EcsIsolatedMysql.assertCheckViolation;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Actual MyBatis task writes + required V3 audit + commit events on admitted ECS MySQL only. */
@EnabledIfSystemProperty(named="doorhandle.report.mysql.config",matches=".+")
class SystemDetectionHistoryMySqlTest {
    static final AtomicBoolean reject=new AtomicBoolean();
    static class Committed {
        final List<BusinessResourceChanged> events=new CopyOnWriteArrayList<>();
        @TransactionalEventListener public void committed(BusinessResourceChanged event){events.add(event);}
    }
    @Configuration @EnableTransactionManagement(proxyTargetClass=true)
    static class Config {
        @Bean(destroyMethod="close") ReportMySqlFixture fixture(){return new ReportMySqlFixture();}
        @Bean DataSource data(ReportMySqlFixture fixture){return fixture.source();}
        @Bean JdbcTemplate jdbc(DataSource data){return new JdbcTemplate(data);}
        @Bean PlatformTransactionManager transactions(DataSource data){return new DataSourceTransactionManager(data);}
        @Bean ObjectMapper json(){return new ObjectMapper().findAndRegisterModules();}
        @Bean DetectionTaskMapper mapper(DataSource data) throws Exception {
            var config=new MybatisConfiguration();config.setMapUnderscoreToCamelCase(true);config.addMapper(DetectionTaskMapper.class);
            var factory=new MybatisSqlSessionFactoryBean();factory.setDataSource(data);factory.setConfiguration(config);
            return new SqlSessionTemplate(factory.getObject()).getMapper(DetectionTaskMapper.class);
        }
        @Bean BusinessUserDirectory users(JdbcTemplate jdbc){return new BusinessUserDirectory(){
            public Identity current(long id,String name){var rows=jdbc.queryForList("SELECT username,role FROM users WHERE id=?",id);
                if(rows.size()!=1||!Objects.equals(name,rows.get(0).get("username")))throw new SecurityException("Current reader absent");
                return new Identity(id,name,"SUPERVISOR".equals(rows.get(0).get("role")));}
            public Identity authenticated(){throw new AssertionError("System execution must not request a logged-in actor");}
        };}
        @Bean DetectionTaskAccessPolicy policy(){return new DetectionTaskAccessPolicy();}
        @Bean AgentUserDirectory assignmentDirectory(){return mock(AgentUserDirectory.class);}
        @Bean DetectionMutationParticipant access(JdbcTemplate jdbc,DetectionTaskAccessPolicy policy){return new DetectionMutationParticipant(jdbc,policy);}
        @Bean com.ruanzhu.doorhandle.module.system.mapper.AccountEmployeeBindingMapper bindings(){return mock(com.ruanzhu.doorhandle.module.system.mapper.AccountEmployeeBindingMapper.class);}
        @Bean com.ruanzhu.doorhandle.contracts.organization.EmployeeDirectoryApi employees(){return mock(com.ruanzhu.doorhandle.contracts.organization.EmployeeDirectoryApi.class);}
        @Bean OperationsAuditService history(JdbcTemplate jdbc,BusinessUserDirectory users){return new OperationsAuditService(jdbc,users);}
        @Bean @Primary SystemChangeAuditApi required(OperationsAuditService history){return event->{if(reject.get())throw new IllegalStateException("required audit unavailable");history.appendSystemChange(event);};}
        @Bean DetectionSystemChanges changes(JdbcTemplate jdbc){return new DetectionSystemChanges(jdbc);}
        @Bean Committed committed(){return new Committed();}
        @Bean DetectionTaskServiceImpl worker(DetectionTaskMapper tasks,ObjectMapper json,DetectionTaskAccessPolicy policy){
            return new DetectionTaskServiceImpl(tasks,mock(com.ruanzhu.doorhandle.module.model.mapper.ModelInfoMapper.class),
                mock(com.ruanzhu.doorhandle.module.model.service.ModelService.class),mock(com.ruanzhu.doorhandle.module.infra.service.OssStorageService.class),
                new com.ruanzhu.doorhandle.module.infra.config.properties.OssProperties(),mock(DetectionTaskDispatchService.class),mock(DetectionNotificationPort.class),json,policy);
        }
    }
    AnnotationConfigApplicationContext context;JdbcTemplate jdbc;DetectionTaskServiceImpl worker;DetectionSystemChanges changes;OperationsAuditService history;Committed committed;
    final AgentActor boss=new AgentActor(2,"boss",AgentActor.Role.SUPERVISOR),outsider=new AgentActor(3,"outsider",AgentActor.Role.INSPECTOR);
    @BeforeEach void setup(){
        SecurityContextHolder.clearContext();reject.set(false);context=new AnnotationConfigApplicationContext();
        context.getEnvironment().getPropertySources().addFirst(new MapPropertySource("system-history",Map.of("operations.audit.enabled","true",
            "collaboration.mutations.enabled","true","collaboration.change-history.enabled","true")));
        context.register(Config.class);context.refresh();jdbc=context.getBean(JdbcTemplate.class);worker=context.getBean(DetectionTaskServiceImpl.class);
        changes=context.getBean(DetectionSystemChanges.class);history=context.getBean(OperationsAuditService.class);committed=context.getBean(Committed.class);
        jdbc.update("INSERT INTO users(id,username,password,role) VALUES(1,'origin','fixture','INSPECTOR'),(2,'boss','fixture','SUPERVISOR'),(3,'outsider','fixture','INSPECTOR')");
        seed("worker-task","dispatch-a");
    }
    @AfterEach void close(){SecurityContextHolder.clearContext();if(context!=null)context.close();}
    void seed(String task,String dispatch){jdbc.update("INSERT INTO detection_task(task_id,task_type,created_by,created_user_id,created_identity_name,status,stage,dispatch_id,total_images,processed_images,successful_images,failed_images) VALUES(?,'BATCH','origin',1,'origin','QUEUED','QUEUED',?,1,0,0,0)",task,dispatch);}
    DetectionTaskFinishedEvent event(String id,String dispatch){return DetectionTaskFinishedEvent.builder().taskId("worker-task").eventId(id).dispatchId(dispatch).status("COMPLETED")
        .totalImages(1).successfulImages(1).failedImages(0).statistics(Map.of("private","https://fixture.invalid/path?secret=never-history"))
        .resultJsonKey("private/result.json").resultOssPrefix("private/location").errorMessage(null).build();}
    long count(){return jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='OPERATIONS'",Long.class);}
    long version(){return jdbc.queryForObject("SELECT version FROM detection_task WHERE task_id='worker-task'",Long.class);}
    JsonNode payload() throws Exception{return context.getBean(ObjectMapper.class).readTree(jdbc.queryForObject("SELECT payload_json FROM audit_event WHERE kind='OPERATIONS' ORDER BY id DESC LIMIT 1",String.class));}
    OperationsAuditService.Filter filter(){return new OperationsAuditService.Filter("DETECTION","DETECTION_TASK","worker-task",null,null,null,null,null);}

    @Test void realWorkerCompletionHasSystemExecutorOriginalInitiatorAndOneCommittedRevision() throws Exception {
        worker.applyFinishedEvent(event("event-one","dispatch-a"));
        assertThat(version()).isEqualTo(1);assertThat(count()).isEqualTo(1);assertThat(committed.events).hasSize(1);
        var row=jdbc.queryForMap("SELECT actor_user_id,owner_user_id,payload_version,operation_actor_key FROM audit_event WHERE kind='OPERATIONS'");
        assertThat(row.get("actor_user_id")).isNull();assertThat(row.get("owner_user_id")).isNull();assertThat(((Number)row.get("payload_version")).intValue()).isEqualTo(3);
        assertThat(row.get("operation_actor_key")).isEqualTo("SYSTEM:DETECTION_WORKER");
        var payload=payload();assertThat(payload.path("source").asText()).isEqualTo("SYSTEM");assertThat(payload.path("initiator").path("userId").asLong()).isEqualTo(1);
        assertThat(payload.toString()).doesNotContain("fixture.invalid","private/location","private/result.json","never-history");
        var item=history.changes(boss,Long.MAX_VALUE,50,filter()).items().get(0);assertThat(item.actor()).isNull();assertThat(item.source().type()).isEqualTo("SYSTEM");
        var latest=history.latest(boss,List.of(new ChangeHistory.ResourceKey("DETECTION","DETECTION_TASK","worker-task"))).get(0).latest();
        assertThat(latest.id()).isEqualTo(item.id());assertThat(latest.actor()).isNull();assertThat(latest.source().type()).isEqualTo("SYSTEM");
        assertThat(history.latest(outsider,List.of(new ChangeHistory.ResourceKey("DETECTION","DETECTION_TASK","worker-task")))).isEmpty();
        assertThat(item.source().initiator().userId()).isEqualTo("1");assertThat(item.beforeVersion()).isEqualTo("0");assertThat(item.afterVersion()).isEqualTo("1");
        assertThat(history.change(boss,item.id()).changes()).anySatisfy(field->{assertThat(field.field()).isEqualTo("status");assertThat(field.before()).isEqualTo("QUEUED");assertThat(field.after()).isEqualTo("COMPLETED");});
    }
    @Test void missingOriginalAccountNeverBlocksAutomaticCompletion() throws Exception {
        jdbc.update("DELETE FROM users WHERE id=1");worker.applyFinishedEvent(event("deleted-origin","dispatch-a"));
        assertThat(version()).isEqualTo(1);assertThat(payload().path("initiator").path("username").asText()).isEqualTo("origin");assertThat(count()).isEqualTo(1);
    }
    @Test void duplicateTerminalAndStaleDispatchEventsDoNotChangeVersionOrCreateMoreHistory(){
        worker.applyFinishedEvent(event("same-event","dispatch-a"));worker.applyFinishedEvent(event("same-event","dispatch-a"));
        worker.applyFinishedEvent(event("another-terminal-event","dispatch-a"));worker.applyFinishedEvent(event("stale","old-dispatch"));
        assertThat(version()).isEqualTo(1);assertThat(count()).isEqualTo(1);assertThat(committed.events).hasSize(1);
    }
    @Test void concurrentRealWorkerRedeliveryCommitsExactlyOneFact() throws Exception {
        var gate=new CyclicBarrier(2);var pool=Executors.newFixedThreadPool(2);
        try{var first=pool.submit(()->{gate.await(10,TimeUnit.SECONDS);worker.applyFinishedEvent(event("concurrent","dispatch-a"));return true;});
            var second=pool.submit(()->{gate.await(10,TimeUnit.SECONDS);worker.applyFinishedEvent(event("concurrent","dispatch-a"));return true;});
            assertThat(first.get(20,TimeUnit.SECONDS)).isTrue();assertThat(second.get(20,TimeUnit.SECONDS)).isTrue();
        }finally{pool.shutdownNow();}
        assertThat(version()).isEqualTo(1);assertThat(count()).isEqualTo(1);assertThat(committed.events).hasSize(1);
    }
    @Test void mandatoryAuditFailureRollsBackActualTaskLastEventRevisionAndNotification(){
        reject.set(true);assertThatThrownBy(()->worker.applyFinishedEvent(event("retry-after-audit","dispatch-a"))).isInstanceOf(DetectionSystemChanges.HistoryFailure.class);
        var row=jdbc.queryForMap("SELECT status,last_finished_event_id,version FROM detection_task WHERE task_id='worker-task'");
        assertThat(row.get("status")).isEqualTo("QUEUED");assertThat(row.get("last_finished_event_id")).isNull();assertThat(version()).isZero();assertThat(count()).isZero();assertThat(committed.events).isEmpty();
        reject.set(false);worker.applyFinishedEvent(event("retry-after-audit","dispatch-a"));assertThat(version()).isEqualTo(1);assertThat(count()).isEqualTo(1);
    }
    @Test void realDispatchFailureIsStableAndItsRawErrorNeverEntersHistory() throws Exception {
        worker.failTask("worker-task","stale-dispatch","must-ignore");assertThat(version()).isZero();assertThat(count()).isZero();
        worker.failTask("worker-task","dispatch-a","https://fixture.invalid/?token=not-in-history");worker.failTask("worker-task","dispatch-a","late-failure");
        assertThat(version()).isEqualTo(1);assertThat(count()).isEqualTo(1);assertThat(payload().path("component").asText()).isEqualTo("DETECTION_WORKER");
        assertThat(payload().toString()).doesNotContain("fixture.invalid","not-in-history","late-failure");
    }
    @Test void localWorkerStartsAndFinishesThroughRealTransactionalWriters(){
        var task=new DetectionTask();task.setTaskId("worker-task");task.setDispatchId("dispatch-a");
        assertThat(changes.startLocal(task)).isTrue();assertThat(version()).isEqualTo(1);assertThat(count()).isEqualTo(1);
        task.setProcessedImages(1);task.setSuccessfulImages(1);task.setFailedImages(0);task.setStatisticsJson("{\"private\":\"body-not-for-history\"}");
        assertThat(changes.finishLocal(task)).isTrue();assertThat(version()).isEqualTo(2);assertThat(count()).isEqualTo(2);assertThat(committed.events).hasSize(2);
        assertThat(changes.finishLocal(task)).isFalse();assertThat(changes.startLocal(task)).isFalse();assertThat(version()).isEqualTo(2);
    }
    @Test void localCompletionAuditFailurePreservesProcessingVersionAndCanRetry(){
        var task=new DetectionTask();task.setTaskId("worker-task");task.setDispatchId("dispatch-a");changes.startLocal(task);
        task.setProcessedImages(1);task.setSuccessfulImages(1);task.setFailedImages(0);reject.set(true);
        assertThatThrownBy(()->changes.finishLocal(task)).isInstanceOf(DetectionSystemChanges.HistoryFailure.class);
        assertThat(version()).isEqualTo(1);assertThat(jdbc.queryForObject("SELECT status FROM detection_task WHERE task_id='worker-task'",String.class)).isEqualTo("PROCESSING");assertThat(count()).isEqualTo(1);
        reject.set(false);assertThat(changes.finishLocal(task)).isTrue();assertThat(version()).isEqualTo(2);assertThat(count()).isEqualTo(2);
    }
    @Test void schemaRejectsUserExecutorInSystemPayloadAndNullExecutorInV2() throws Exception {
        worker.applyFinishedEvent(event("event-one","dispatch-a"));var value=(ObjectNode)payload();value.put("sourceEventId","guard-event");value.put("causationRequestId","guard-event");
        String rows="SELECT * FROM audit_event WHERE kind='OPERATIONS' ORDER BY id";
        var original=jdbc.queryForList(rows);assertThat(original).hasSize(1);
        String insert="INSERT INTO audit_event(event_id,kind,owner_user_id,actor_user_id,resource_type,resource_id,request_id,action,payload_version,payload_json) VALUES(UUID(),'OPERATIONS',?,?,'OPERATIONS','worker-task','guard-event','SYSTEM_COMPLETED',?,?)";
        assertCheckViolation(()->jdbc.update(insert,1L,1L,3,value.toString()),"ck_audit_operations");
        assertThat(jdbc.queryForList(rows)).hasSize(1).isEqualTo(original);
        var userValue=value.deepCopy();userValue.remove(List.of("source","component","sourceEventId","initiator"));
        userValue.put("actorUsername","origin");userValue.putNull("actorDisplayName");userValue.put("actorRole","INSPECTOR");
        assertCheckViolation(()->jdbc.update(insert,null,null,2,userValue.toString()),"ck_audit_operations");
        assertThat(jdbc.queryForList(rows)).hasSize(1).isEqualTo(original);
        value.put("source","USER");assertCheckViolation(()->jdbc.update(insert,null,null,3,value.toString()),"ck_audit_operation_versions");
        assertThat(jdbc.queryForList(rows)).hasSize(1).isEqualTo(original);assertThat(count()).isEqualTo(1);
    }
    @Test void nullSystemActorNeverGrantsPersonalHistoryAndCurrentResourceRevocationStillApplies(){
        worker.applyFinishedEvent(event("event-one","dispatch-a"));var item=history.changes(boss,Long.MAX_VALUE,50,filter()).items().get(0);
        assertThat(history.changes(outsider,Long.MAX_VALUE,50,filter()).items()).isEmpty();assertThatThrownBy(()->history.change(outsider,item.id())).isInstanceOf(SecurityException.class);
        jdbc.update("DELETE FROM detection_task WHERE task_id='worker-task'");assertThatThrownBy(()->history.change(boss,item.id())).isInstanceOf(SecurityException.class);
        assertThat(count()).isEqualTo(1);
    }
    @Test void generatedSystemIdentityDeduplicatesNullActorAndRejectsDifferentFactForSameEvent() throws Exception {
        worker.applyFinishedEvent(event("event-one","dispatch-a"));var value=payload();
        List<ChangeHistory.Change> fields=context.getBean(ObjectMapper.class).convertValue(value.path("changes"),new com.fasterxml.jackson.core.type.TypeReference<>(){});
        var fact=new SystemChangeAuditApi.Event(SystemChangeAuditApi.Component.DETECTION_WORKER,"event-one",new SystemChangeAuditApi.Initiator(1L,"origin"),
            "DETECTION","DETECTION_TASK","worker-task","SYSTEM_COMPLETED","event-one",0L,1L,fields);
        var tx=new org.springframework.transaction.support.TransactionTemplate(context.getBean(PlatformTransactionManager.class));
        var port=context.getBean(SystemChangeAuditApi.class);tx.executeWithoutResult(status->port.appendSystemChange(fact));
        assertThat(count()).isEqualTo(1);assertThat(committed.events).hasSize(1);
        var changed=new SystemChangeAuditApi.Event(fact.component(),fact.sourceEventId(),fact.initiator(),fact.domain(),fact.resourceType(),fact.resourceId(),fact.action(),fact.requestId(),0L,1L,
            List.of(new ChangeHistory.Change("status","检测状态","REPLACE","QUEUED","FAILED",null,false)));
        assertThatThrownBy(()->tx.executeWithoutResult(status->port.appendSystemChange(changed))).isInstanceOf(IllegalStateException.class);
        assertThat(count()).isEqualTo(1);assertThat(version()).isEqualTo(1);
    }
}
