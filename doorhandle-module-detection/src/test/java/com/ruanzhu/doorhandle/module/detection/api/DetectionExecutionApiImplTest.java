package com.ruanzhu.doorhandle.module.detection.api;

import com.baomidou.mybatisplus.annotation.*;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.extension.spring.MybatisSqlSessionFactoryBean;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.detection.service.*;
import com.ruanzhu.doorhandle.module.detection.service.detection.*;
import com.ruanzhu.doorhandle.module.detection.service.impl.DetectionTaskServiceImpl;
import com.ruanzhu.doorhandle.module.infra.config.properties.OssProperties;
import com.ruanzhu.doorhandle.module.infra.service.OssStorageService;
import com.ruanzhu.doorhandle.module.model.mapper.ModelInfoMapper;
import com.ruanzhu.doorhandle.module.model.service.ModelService;
import org.junit.jupiter.api.*;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.transaction.support.TransactionTemplate;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Actual MyBatis SQL plus JDBC transaction/outbox; no network or model calls. */
class DetectionExecutionApiImplTest {
    JdbcTemplate jdbc;TransactionTemplate tx;DetectionTaskMapper tasks;
    DetectionExecutionApiImpl api;DetectionDispatchOutbox outbox;
    BusinessUserDirectory users;OperationsAuditApi audit;
    ObjectMapper json=new ObjectMapper().findAndRegisterModules();
    AgentActor employee=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);
    AgentActor other=new AgentActor(2,"bob",AgentActor.Role.INSPECTOR);
    AgentActor supervisor=new AgentActor(3,"chief",AgentActor.Role.SUPERVISOR);
    AtomicBoolean failAudit=new AtomicBoolean();
    @BeforeEach void setup() throws Exception {
        var source=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1;LOCK_TIMEOUT=5000","sa","");
        boolean mysql=System.getProperty("detection.command.mysql-file")!=null;
        if(mysql) {
            var settings=json.readTree(java.nio.file.Files.readString(java.nio.file.Path.of(System.getProperty("detection.command.mysql-file"))));
            String database=settings.path("database").asText(),url=settings.path("url").asText();
            if(!database.matches("doorhandle_detection_verify_[a-f0-9]{10}") || !url.startsWith("jdbc:mysql://127.0.0.1:3306/"+database+"?"))
                throw new SecurityException("Only a dedicated local detection verification database is allowed");
            source=new DriverManagerDataSource(url,settings.path("username").asText(),settings.path("password").asText());
        }
        jdbc=new JdbcTemplate(source);tx=new TransactionTemplate(new DataSourceTransactionManager(source));
        if(mysql)for(var table:List.of("test_audit","detection_execution_command","detection_dispatch_outbox","detection_worker_receipt","detection_task"))jdbc.execute("DROP TABLE IF EXISTS "+table);
        var columns=new ArrayList<String>();
        for(var field:DetectionTask.class.getDeclaredFields()) {
            var column=field.getAnnotation(TableField.class);var id=field.getAnnotation(TableId.class);
            if(id!=null){columns.add("id BIGINT AUTO_INCREMENT PRIMARY KEY");continue;}
            if(column==null)continue;
            Class<?> type=field.getType();
            String sqlType=type==Integer.class?"INT":type==Long.class?"BIGINT":type==Boolean.class?"BOOLEAN":type==BigDecimal.class?"DECIMAL(16,6)":type==LocalDateTime.class?"DATETIME(6)":mysql?"MEDIUMTEXT":"VARCHAR(12000)";
            if("task_id".equals(column.value()))sqlType="VARCHAR(128)";
            columns.add(column.value()+" "+sqlType);
        }
        jdbc.execute("CREATE TABLE detection_task("+String.join(",",columns)+",UNIQUE(task_id))");
        String migration=new String(getClass().getResourceAsStream("/db/migration-V42-detection-execution.sql").readAllBytes(),StandardCharsets.UTF_8);
        if(!mysql)migration=migration.replaceAll("(?m)^ KEY idx[^\\n]*\\n","").replaceAll(",\\s*\\)",")")
                .replace("ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin","").replaceAll("\\bJSON\\b","VARCHAR(12000)");
        try(var connection=source.getConnection()){org.springframework.jdbc.datasource.init.ScriptUtils.executeSqlScript(connection,new org.springframework.core.io.ByteArrayResource(migration.getBytes(StandardCharsets.UTF_8)));}
        jdbc.execute("CREATE TABLE test_audit(actor BIGINT,resource VARCHAR(128),action VARCHAR(64),request_id VARCHAR(128))");
        var config=new MybatisConfiguration();config.setMapUnderscoreToCamelCase(true);config.addMapper(DetectionTaskMapper.class);
        var factory=new MybatisSqlSessionFactoryBean();factory.setDataSource(source);factory.setConfiguration(config);
        tasks=new SqlSessionTemplate(factory.getObject()).getMapper(DetectionTaskMapper.class);
        users=mock(BusinessUserDirectory.class);
        for(var actor:List.of(employee,other,supervisor))when(users.current(actor.userId(),actor.username())).thenReturn(new BusinessUserDirectory.Identity(actor.userId(),actor.username(),actor.supervisor()));
        audit=event->{if(failAudit.get()&&"RETRY_ACCEPTED".equals(event.action()))throw new IllegalStateException("injected audit failure");jdbc.update("INSERT INTO test_audit VALUES(?,?,?,?)",event.actor().userId(),event.resourceId(),event.action(),event.requestId());};
        var publisher=mock(DetectionTaskEventPublisher.class);
        outbox=new DetectionDispatchOutbox(jdbc,tx.getTransactionManager(),json,publisher,users,audit);
        var access=new DetectionTaskAccessPolicy();
        var storage=mock(OssStorageService.class);when(storage.getBucketName()).thenReturn("private");
        var service=new DetectionTaskServiceImpl(tasks,mock(ModelInfoMapper.class),mock(ModelService.class),storage,new OssProperties(),mock(DetectionTaskDispatchService.class),mock(DetectionNotificationPort.class),json,access);
        service.setOutbox(outbox);
        api=new DetectionExecutionApiImpl(tasks,service,access,users,audit,jdbc,json);api.verifySchema();
        var task=new DetectionTask();task.setTaskId("task-1");task.setCreatedBy("alice");task.setModelId(12);task.setThreshold(new BigDecimal("0.5"));
        task.setStatus("FAILED");task.setFlowStatus("FAILED");task.setStage("FAILED");task.setOriginalImageKeysJson("[\"private/originals/one.jpg\"]");task.setSourceOssPrefix("private/originals/");
        task.setTotalImages(1);task.setDispatchId("dispatch-old");task.setLastFinishedEventId("finished-old");task.setFinishedAt(LocalDateTime.of(2026,10,21,15,0));
        task.setReviewConclusion("CONFIRMED_DEFECT");task.setReviewer("chief");task.setReviewStatus("REVIEWED");task.setReviewedAt(task.getFinishedAt());
        task.setResultJsonOssKey("private/old-result.json");task.setStatisticsJson("{\"old\":true}");task.setPreviewImageKeysJson("[\"private/old.jpg\"]");task.setDispositionRemark("old disposition");task.setDispositionOperator("chief");
        task.setUpdatedAt(task.getFinishedAt());tasks.insert(task);
        String result=json.writeValueAsString(Map.of("taskId","task-1","dispatchId","dispatch-old","eventType","DETECTION_TASK_FINISHED","status","FAILED"));
        jdbc.update("INSERT INTO detection_worker_receipt(task_id,dispatch_id,event_id,payload_sha256,owner_id,status,result_json,result_sha256,started_at,updated_at) VALUES('task-1','dispatch-old','old-event','fingerprint','old-owner','COMPLETED',?,?,CURRENT_TIMESTAMP(6),CURRENT_TIMESTAMP(6))",result,hash(result));
    }
    @AfterEach void close(){if(outbox!=null)outbox.close();}
    DetectionExecutionApi.RetryApproval approval(){var p=api.previewRetry(employee,"task-1");return new DetectionExecutionApi.RetryApproval(p.taskId(),p.resourceVersion());}
    DetectionExecutionApi.Receipt apply(String request,String proposal,DetectionExecutionApi.RetryApproval approval){return tx.execute(status->api.retry(employee,request,proposal,approval));}
    long count(String table){return jdbc.queryForObject("SELECT COUNT(*) FROM "+table,Long.class);}

    @Test void atomicReceiptAndOutboxResetNullsUsingActualMapperSql() {
        var preview=api.previewRetry(employee,"task-1");assertThat(preview.imageCount()).isEqualTo(1);
        assertThat(json.valueToTree(preview).toString()).doesNotContain("private/");
        var receipt=apply("request-1","proposal-1",approval());
        var task=tasks.selectById(1L);
        assertThat(task.getStatus()).isEqualTo("QUEUED");assertThat(task.getDispatchId()).isEqualTo(receipt.dispatchId()).isNotEqualTo("dispatch-old");
        assertThat(task.getResultJsonOssKey()).isNull();assertThat(task.getStatisticsJson()).isNull();assertThat(task.getReviewer()).isNull();assertThat(task.getReviewConclusion()).isNull();
        assertThat(task.getReviewedAt()).isNull();assertThat(task.getDispositionRemark()).isNull();assertThat(task.getDispositionOperator()).isNull();assertThat(task.getLastFinishedEventId()).isNull();
        assertThat(count("detection_execution_command")).isEqualTo(1);assertThat(count("detection_dispatch_outbox")).isEqualTo(1);assertThat(count("test_audit")).isEqualTo(2);
        assertThat(api.receipt(employee,"request-1")).contains(receipt);
    }
    @Test void repeatedConfirmationReturnsOriginalReceiptWithoutAnotherDispatch() {
        var approval=approval();var receipt=apply("request-1","proposal-1",approval);
        assertThat(apply("request-1","proposal-1",approval)).isEqualTo(receipt);
        assertThat(count("detection_dispatch_outbox")).isEqualTo(1);assertThat(count("test_audit")).isEqualTo(2);
        assertThatThrownBy(()->apply("request-1","changed-proposal",approval)).isInstanceOf(IllegalArgumentException.class);
    }
    @Test void staleSnapshotCannotResetTaskOrQueueWork() {
        var approved=approval();jdbc.update("UPDATE detection_task SET assignee='bob' WHERE task_id='task-1'");
        assertThatThrownBy(()->apply("request-1","proposal-1",approved)).isInstanceOf(DetectionExecutionApi.ResourceChanged.class);
        assertThat(count("detection_dispatch_outbox")).isZero();assertThat(count("test_audit")).isZero();
    }
    @Test void auditFailureRollsBackBusinessStateOutboxAndReceipt() {
        var approved=approval();failAudit.set(true);
        assertThatThrownBy(()->apply("request-1","proposal-1",approved)).isInstanceOf(IllegalStateException.class).hasMessage("injected audit failure");
        assertThat(tasks.selectById(1L).getDispatchId()).isEqualTo("dispatch-old");assertThat(tasks.selectById(1L).getResultJsonOssKey()).isEqualTo("private/old-result.json");
        assertThat(count("detection_execution_command")).isZero();assertThat(count("detection_dispatch_outbox")).isZero();assertThat(count("test_audit")).isZero();
    }
    @Test void foreignAccountAndRevokedSupervisorCannotAccessTaskOrReceipt() {
        assertThatThrownBy(()->api.assertReadable(other,"task-1")).isInstanceOf(SecurityException.class);
        assertThatThrownBy(()->api.previewRetry(other,"task-1")).isInstanceOf(SecurityException.class);
        var approved=approval();apply("request-1","proposal-1",approved);
        assertThat(api.receipt(other,"request-1")).isEmpty();
        when(users.current(3,"chief")).thenReturn(new BusinessUserDirectory.Identity(3,"chief",false));
        assertThatThrownBy(()->api.previewRetry(supervisor,"task-1")).isInstanceOf(SecurityException.class);
    }
    @Test void unknownPreviousWriteIsNotReplayedAndNoMutationIsSaved() {
        for(String status:List.of("RUNNING","NEEDS_REVIEW")) {
            jdbc.update("UPDATE detection_worker_receipt SET status=?",status);
            assertThatThrownBy(()->api.previewRetry(employee,"task-1")).isInstanceOf(DetectionExecutionApi.NeedsReview.class);
        }
        jdbc.update("DELETE FROM detection_worker_receipt");
        assertThatThrownBy(()->api.previewRetry(employee,"task-1")).isInstanceOf(DetectionExecutionApi.NeedsReview.class);
        assertThat(count("detection_dispatch_outbox")).isZero();
    }
    @Test void unknownWriteAppearingAfterPreviewPreventsApprovedExecution() {
        var approved=approval();jdbc.update("UPDATE detection_worker_receipt SET status='NEEDS_REVIEW'");
        assertThatThrownBy(()->apply("request-1","proposal-1",approved)).isInstanceOf(DetectionExecutionApi.NeedsReview.class);
        assertThat(count("detection_execution_command")).isZero();
    }
    @Test void corruptCompletedReceiptCannotAuthorizeRetry() {
        jdbc.update("UPDATE detection_worker_receipt SET result_json='{}'");
        assertThatThrownBy(()->api.previewRetry(employee,"task-1")).isInstanceOf(DetectionExecutionApi.NeedsReview.class);
    }
    @Test void closedOrActiveTaskCannotBeRetriedEvenWithOldFailedFlow() {
        for(String flow:List.of("RELEASED","SCRAPPED","ARCHIVED")) {
            jdbc.update("UPDATE detection_task SET flow_status=?",flow);
            assertThatThrownBy(()->api.previewRetry(employee,"task-1")).isInstanceOf(com.ruanzhu.doorhandle.common.BusinessException.class);
        }
        jdbc.update("UPDATE detection_task SET status='PROCESSING',flow_status='FAILED'");
        assertThatThrownBy(()->api.previewRetry(employee,"task-1")).isInstanceOf(com.ruanzhu.doorhandle.common.BusinessException.class);
    }
    @Test void noTransactionCannotMutateAnything() {
        var approved=approval();assertThatThrownBy(()->api.retry(employee,"request-1","proposal-1",approved)).isInstanceOf(IllegalStateException.class);
        assertThat(count("detection_dispatch_outbox")).isZero();
    }
    @Test void twoConcurrentConfirmationsClaimOneDispatch() throws Exception {
        var approved=approval();var pool=Executors.newFixedThreadPool(2);var gate=new CountDownLatch(1);
        try {
            Callable<DetectionExecutionApi.Receipt> work=()->{gate.await();return apply("request-1","proposal-1",approved);};
            var first=pool.submit(work);var second=pool.submit(work);gate.countDown();
            assertThat(first.get(10,TimeUnit.SECONDS)).isEqualTo(second.get(10,TimeUnit.SECONDS));
        } finally {pool.shutdownNow();}
        assertThat(count("detection_dispatch_outbox")).isEqualTo(1);
    }
    @Test void competingDistinctApprovalsCannotBothUseTheSameResourceVersion() throws Exception {
        var approved=approval();var pool=Executors.newFixedThreadPool(2);var gate=new CountDownLatch(1);
        try {
            Callable<String> first=()->{gate.await();try{apply("request-first","proposal-first",approved);return "ACCEPTED";}catch(DetectionExecutionApi.ResourceChanged stale){return "STALE";}};
            Callable<String> second=()->{gate.await();try{apply("request-second","proposal-second",approved);return "ACCEPTED";}catch(DetectionExecutionApi.ResourceChanged stale){return "STALE";}};
            var a=pool.submit(first);var b=pool.submit(second);gate.countDown();
            assertThat(List.of(a.get(10,TimeUnit.SECONDS),b.get(10,TimeUnit.SECONDS))).containsExactlyInAnyOrder("ACCEPTED","STALE");
        } finally {pool.shutdownNow();}
        assertThat(count("detection_execution_command")).isEqualTo(1);assertThat(count("detection_dispatch_outbox")).isEqualTo(1);
    }
    private static String hash(String value) throws Exception {return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}
}
