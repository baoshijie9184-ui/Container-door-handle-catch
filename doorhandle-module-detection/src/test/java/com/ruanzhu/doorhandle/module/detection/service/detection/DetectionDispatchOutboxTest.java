package com.ruanzhu.doorhandle.module.detection.service.detection;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.detection.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.transaction.support.TransactionTemplate;
import java.math.BigDecimal;
import java.util.*;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class DetectionDispatchOutboxTest {
    JdbcTemplate jdbc;TransactionTemplate tx;ObjectMapper json=new ObjectMapper();
    DetectionTaskEventPublisher publisher;BusinessUserDirectory users;OperationsAuditApi audit;DetectionDispatchOutbox service,other;
    AgentActor actor=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);
    @BeforeEach void setup() throws Exception {
        var source=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa","");
        jdbc=new JdbcTemplate(source);tx=new TransactionTemplate(new DataSourceTransactionManager(source));
        String sql=new String(getClass().getResourceAsStream("/db/migration-V42-detection-execution.sql").readAllBytes(),java.nio.charset.StandardCharsets.UTF_8)
                .replaceAll("(?m)^ KEY idx[^\\n]*\\n","").replaceAll(",\\s*\\)",")").replace("ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin","");
        try(var connection=source.getConnection()){org.springframework.jdbc.datasource.init.ScriptUtils.executeSqlScript(connection,new org.springframework.core.io.ByteArrayResource(sql.getBytes(java.nio.charset.StandardCharsets.UTF_8)));}
        jdbc.execute("CREATE TABLE business_record(id INT PRIMARY KEY,changed INT)");jdbc.update("INSERT INTO business_record VALUES(1,0)");
        publisher=mock(DetectionTaskEventPublisher.class);users=mock(BusinessUserDirectory.class);audit=mock(OperationsAuditApi.class);
        when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",false));
        service=new DetectionDispatchOutbox(jdbc,tx.getTransactionManager(),json,publisher,users,audit);service.validate();
        other=new DetectionDispatchOutbox(jdbc,tx.getTransactionManager(),json,publisher,users,audit);
    }
    @AfterEach void close(){service.close();other.close();}
    DetectionTaskCreatedEvent event(String id){return DetectionTaskCreatedEvent.builder().eventId(id).eventType("DETECTION_TASK_CREATED").eventTime("2026-10-21T14:00:00+08:00").taskId("task-1").dispatchId("dispatch-1").bucketName("private-bucket").sourcePrefix("private/source/").originalKeys(List.of("private/source/one.jpg")).captureInfo(DetectionTaskEventCaptureInfo.builder().region("beijing").collector("alice").build()).modelId(1).threshold(new BigDecimal("0.5")).build();}
    String enqueue(String id){return tx.execute(status->service.enqueue(event(id),actor,"request-1"));}

    @Test void duplicateDispatchKeepsTheOriginalEventAndDecodedPayloadIncludesCaptureInfo(){
        assertThat(enqueue("event-1")).isEqualTo("event-1");assertThat(enqueue("event-2")).isEqualTo("event-1");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM detection_dispatch_outbox",Long.class)).isEqualTo(1);
        assertThat(service.publishOne()).isTrue();assertThat(service.publishOne()).isFalse();
        var captured=org.mockito.ArgumentCaptor.forClass(DetectionTaskCreatedEvent.class);verify(publisher).publishCreated(captured.capture());
        assertThat(captured.getValue().getEventId()).isEqualTo("event-1");assertThat(captured.getValue().getCaptureInfo().getCollector()).isEqualTo("alice");
        assertThat(jdbc.queryForObject("SELECT status FROM detection_dispatch_outbox",String.class)).isEqualTo("SENT");
    }
    @Test void auditFailureRollsBackBusinessWriteAndOutboxTogether(){
        doThrow(new IllegalStateException("audit unavailable")).when(audit).append(any());
        assertThatThrownBy(()->tx.executeWithoutResult(status->{jdbc.update("UPDATE business_record SET changed=1");service.enqueue(event("event-1"),actor,"request-1");})).hasMessage("audit unavailable");
        assertThat(jdbc.queryForObject("SELECT changed FROM business_record",Integer.class)).isZero();assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM detection_dispatch_outbox",Integer.class)).isZero();verifyNoInteractions(publisher);
    }
    @Test void enqueueWithoutBusinessTransactionOrWithChangedPayloadFailsClosed(){
        assertThatThrownBy(()->service.enqueue(event("event-1"),actor,"request-1")).hasMessageContaining("同一事务");
        enqueue("event-1");var modified=event("event-2");modified.setThreshold(new BigDecimal("0.8"));
        assertThatThrownBy(()->tx.executeWithoutResult(status->service.enqueue(modified,actor,"request-2"))).hasMessageContaining("内容冲突");verifyNoInteractions(publisher);
    }
    @Test void uncertainBrokerAcknowledgementOnlyResendsExactlyTheStoredEvent(){
        enqueue("event-1");doThrow(new IllegalStateException("ack lost")).doNothing().when(publisher).publishCreated(any());
        service.publishOne();assertThat(jdbc.queryForObject("SELECT status FROM detection_dispatch_outbox",String.class)).isEqualTo("PENDING");
        jdbc.update("UPDATE detection_dispatch_outbox SET next_attempt_at=?",java.time.LocalDateTime.of(2020,1,1,0,0));
        other.publishOne();var captured=org.mockito.ArgumentCaptor.forClass(DetectionTaskCreatedEvent.class);verify(publisher,times(2)).publishCreated(captured.capture());
        assertThat(captured.getAllValues().get(0)).isEqualTo(captured.getAllValues().get(1));assertThat(jdbc.queryForObject("SELECT attempts FROM detection_dispatch_outbox",Integer.class)).isEqualTo(2);
    }
    @Test void validJsonWithChangedContentsIsHeldForReviewInsteadOfPublished(){
        enqueue("event-1");var changed=event("event-1");changed.setBucketName("changed-bucket");
        jdbc.update("UPDATE detection_dispatch_outbox SET payload_json=?",json.valueToTree(changed).toString());service.publishOne();
        assertThat(jdbc.queryForObject("SELECT status FROM detection_dispatch_outbox",String.class)).isEqualTo("NEEDS_REVIEW");verifyNoInteractions(publisher);
    }
    @Test void concurrentDeliveryAndExpiredLeaseCannotLetTheOldOwnerOverwriteTheNewReceipt() throws Exception {
        enqueue("event-1");var entered=new CountDownLatch(1);var release=new CountDownLatch(1);var attempts=new java.util.concurrent.atomic.AtomicInteger();
        doAnswer(call->{if(attempts.getAndIncrement()==0){entered.countDown();if(!release.await(5,TimeUnit.SECONDS))throw new IllegalStateException("test deadline");throw new IllegalStateException("old acknowledgement lost");}return null;}).when(publisher).publishCreated(any());
        var executor=Executors.newSingleThreadExecutor();
        try{
            var first=executor.submit(()->service.publishOne());assertThat(entered.await(3,TimeUnit.SECONDS)).isTrue();
            assertThat(other.publishOne()).isFalse();
            jdbc.update("UPDATE detection_dispatch_outbox SET lease_until=?",java.time.LocalDateTime.of(2020,1,1,0,0));
            assertThat(other.publishOne()).isTrue();release.countDown();assertThat(first.get(5,TimeUnit.SECONDS)).isTrue();
            assertThat(jdbc.queryForObject("SELECT status FROM detection_dispatch_outbox",String.class)).isEqualTo("SENT");
        }finally{release.countDown();executor.shutdownNow();}
    }
}
