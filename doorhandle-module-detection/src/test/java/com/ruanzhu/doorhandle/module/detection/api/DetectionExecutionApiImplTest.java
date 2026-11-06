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
    com.ruanzhu.doorhandle.module.detection.support.CompactDetectionMySqlFixture fixture;
    JdbcTemplate jdbc;TransactionTemplate tx;DetectionTaskMapper tasks;
    DetectionExecutionApiImpl api;DetectionDispatchOutbox outbox;
    BusinessUserDirectory users;OperationsAuditApi audit;
    ObjectMapper json=new ObjectMapper().findAndRegisterModules();
    AgentActor employee=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);
    AgentActor other=new AgentActor(2,"bob",AgentActor.Role.INSPECTOR);
    AgentActor supervisor=new AgentActor(3,"chief",AgentActor.Role.SUPERVISOR);
    AtomicBoolean failAudit=new AtomicBoolean();
    @BeforeEach void setup() throws Exception {
        fixture=new com.ruanzhu.doorhandle.module.detection.support.CompactDetectionMySqlFixture("detection.command.mysql-file");
        var source=fixture.source();
        jdbc=new JdbcTemplate(source);tx=new TransactionTemplate(new DataSourceTransactionManager(source));
        fixture.ownFixtureTable("test_audit");
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
        jdbc.update("INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,resource_type,resource_id,run_id,claim_token,fence,status,payload_version,payload_json,result_version,result_json,result_sha256,created_at,updated_at) VALUES(?, 'DETECTION_WORKER','DETECTION_WORKER','old-event',?,0,'DETECTION_TASK','task-1','dispatch-old','old-owner',1,'COMPLETED',1,'{\"schemaVersion\":1}',1,?,?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",
                "det-worker:"+hash(json.writeValueAsString(List.of("task-1","dispatch-old"))).substring(0,48),hash("fingerprint"),result,hash(result));
    }
    @AfterEach void close(){if(outbox!=null)outbox.close();if(fixture!=null)fixture.close();}
    DetectionExecutionApi.RetryApproval approval(){var p=api.previewRetry(employee,"task-1");return new DetectionExecutionApi.RetryApproval(p.taskId(),p.resourceVersion());}
    DetectionExecutionApi.Receipt apply(String request,String proposal,DetectionExecutionApi.RetryApproval approval){return tx.execute(status->api.retry(employee,request,proposal,approval));}
    long count(String kind){
        if("test_audit".equals(kind))return jdbc.queryForObject("SELECT COUNT(*) FROM test_audit",Long.class);
        if(!Set.of("DETECTION_COMMAND","DETECTION_DISPATCH").contains(kind))throw new IllegalArgumentException();
        return jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind=?",Long.class,kind);
    }

    @Test void atomicReceiptAndOutboxResetNullsUsingActualMapperSql() {
        var preview=api.previewRetry(employee,"task-1");assertThat(preview.imageCount()).isEqualTo(1);
        assertThat(json.valueToTree(preview).toString()).doesNotContain("private/");
        var receipt=apply("request-1","proposal-1",approval());
        var task=tasks.selectById(1L);
        assertThat(task.getStatus()).isEqualTo("QUEUED");assertThat(task.getDispatchId()).isEqualTo(receipt.dispatchId()).isNotEqualTo("dispatch-old");
        assertThat(task.getResultJsonOssKey()).isNull();assertThat(task.getStatisticsJson()).isNull();assertThat(task.getReviewer()).isNull();assertThat(task.getReviewConclusion()).isNull();
        assertThat(task.getReviewedAt()).isNull();assertThat(task.getDispositionRemark()).isNull();assertThat(task.getDispositionOperator()).isNull();assertThat(task.getLastFinishedEventId()).isNull();
        assertThat(count("DETECTION_COMMAND")).isEqualTo(1);assertThat(count("DETECTION_DISPATCH")).isEqualTo(1);assertThat(count("test_audit")).isEqualTo(2);
        assertThat(api.receipt(employee,"request-1")).contains(receipt);
    }
    @Test void repeatedConfirmationReturnsOriginalReceiptWithoutAnotherDispatch() {
        var approval=approval();var receipt=apply("request-1","proposal-1",approval);
        assertThat(apply("request-1","proposal-1",approval)).isEqualTo(receipt);
        assertThat(count("DETECTION_DISPATCH")).isEqualTo(1);assertThat(count("test_audit")).isEqualTo(2);
        assertThatThrownBy(()->apply("request-1","changed-proposal",approval)).isInstanceOf(IllegalArgumentException.class);
    }
    @Test void staleSnapshotCannotResetTaskOrQueueWork() {
        var approved=approval();jdbc.update("UPDATE detection_task SET assignee='bob' WHERE task_id='task-1'");
        assertThatThrownBy(()->apply("request-1","proposal-1",approved)).isInstanceOf(DetectionExecutionApi.ResourceChanged.class);
        assertThat(count("DETECTION_DISPATCH")).isZero();assertThat(count("test_audit")).isZero();
    }
    @Test void auditFailureRollsBackBusinessStateOutboxAndReceipt() {
        var approved=approval();failAudit.set(true);
        assertThatThrownBy(()->apply("request-1","proposal-1",approved)).isInstanceOf(IllegalStateException.class).hasMessage("injected audit failure");
        assertThat(tasks.selectById(1L).getDispatchId()).isEqualTo("dispatch-old");assertThat(tasks.selectById(1L).getResultJsonOssKey()).isEqualTo("private/old-result.json");
        assertThat(count("DETECTION_COMMAND")).isZero();assertThat(count("DETECTION_DISPATCH")).isZero();assertThat(count("test_audit")).isZero();
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
            jdbc.update("UPDATE workflow_instance SET status=?,result_json=NULL,result_sha256=NULL,result_version=NULL,finished_at=NULL WHERE kind='DETECTION_WORKER'",status);
            assertThatThrownBy(()->api.previewRetry(employee,"task-1")).isInstanceOf(DetectionExecutionApi.NeedsReview.class);
        }
        jdbc.update("DELETE FROM workflow_instance WHERE kind='DETECTION_WORKER'");
        assertThatThrownBy(()->api.previewRetry(employee,"task-1")).isInstanceOf(DetectionExecutionApi.NeedsReview.class);
        assertThat(count("DETECTION_DISPATCH")).isZero();
    }
    @Test void unknownWriteAppearingAfterPreviewPreventsApprovedExecution() {
        var approved=approval();jdbc.update("UPDATE workflow_instance SET status='NEEDS_REVIEW',result_json=NULL,result_sha256=NULL,result_version=NULL,finished_at=NULL WHERE kind='DETECTION_WORKER'");
        assertThatThrownBy(()->apply("request-1","proposal-1",approved)).isInstanceOf(DetectionExecutionApi.NeedsReview.class);
        assertThat(count("DETECTION_COMMAND")).isZero();
    }
    @Test void corruptCompletedReceiptCannotAuthorizeRetry() {
        jdbc.update("UPDATE workflow_instance SET result_json='{}',result_sha256=SHA2('{}',256) WHERE kind='DETECTION_WORKER'");
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
        assertThat(count("DETECTION_DISPATCH")).isZero();
    }
    @Test void twoConcurrentConfirmationsClaimOneDispatch() throws Exception {
        var approved=approval();var pool=Executors.newFixedThreadPool(2);var gate=new CountDownLatch(1);
        try {
            Callable<DetectionExecutionApi.Receipt> work=()->{gate.await();return apply("request-1","proposal-1",approved);};
            var first=pool.submit(work);var second=pool.submit(work);gate.countDown();
            assertThat(first.get(10,TimeUnit.SECONDS)).isEqualTo(second.get(10,TimeUnit.SECONDS));
        } finally {pool.shutdownNow();}
        assertThat(count("DETECTION_DISPATCH")).isEqualTo(1);
    }
    @Test void competingDistinctApprovalsCannotBothUseTheSameResourceVersion() throws Exception {
        var approved=approval();var pool=Executors.newFixedThreadPool(2);var gate=new CountDownLatch(1);
        try {
            Callable<String> first=()->{gate.await();try{apply("request-first","proposal-first",approved);return "ACCEPTED";}catch(DetectionExecutionApi.ResourceChanged stale){return "STALE";}};
            Callable<String> second=()->{gate.await();try{apply("request-second","proposal-second",approved);return "ACCEPTED";}catch(DetectionExecutionApi.ResourceChanged stale){return "STALE";}};
            var a=pool.submit(first);var b=pool.submit(second);gate.countDown();
            assertThat(List.of(a.get(10,TimeUnit.SECONDS),b.get(10,TimeUnit.SECONDS))).containsExactlyInAnyOrder("ACCEPTED","STALE");
        } finally {pool.shutdownNow();}
        assertThat(count("DETECTION_COMMAND")).isEqualTo(1);assertThat(count("DETECTION_DISPATCH")).isEqualTo(1);
    }
    private static String hash(String value) throws Exception {return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}
}
