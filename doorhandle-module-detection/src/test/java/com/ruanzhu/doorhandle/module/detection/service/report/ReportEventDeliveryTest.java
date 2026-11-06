package com.ruanzhu.doorhandle.module.detection.service.report;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.detection.ReportLifecycleEvent;
import com.ruanzhu.doorhandle.module.detection.config.properties.ReportEventProperties;
import com.ruanzhu.doorhandle.module.detection.repository.ReportEventRepository;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;

@org.junit.jupiter.api.condition.EnabledIfSystemProperty(named="doorhandle.report.mysql.config",matches=".+")
class ReportEventDeliveryTest {
    com.ruanzhu.doorhandle.module.detection.support.ReportMySqlFixture fixture;
    JdbcTemplate jdbc;ReportEventRepository repository;ReportEventCodec codec;ReportEventInbox inbox;ReportEventProperties properties;
    MutableClock clock;ObjectMapper json=new ObjectMapper();String report;
    @BeforeEach void setup()throws Exception{
        fixture=new com.ruanzhu.doorhandle.module.detection.support.ReportMySqlFixture();var data=fixture.source();jdbc=new JdbcTemplate(data);
        repository=new ReportEventRepository(jdbc);codec=new ReportEventCodec(json);inbox=new ReportEventInbox(jdbc,repository,codec,new DataSourceTransactionManager(data));
        properties=new ReportEventProperties();clock=new MutableClock(jdbc);report="qr-"+UUID.randomUUID();
    }
    @AfterEach void close(){if(fixture!=null)fixture.close();}
    ReportLifecycleEvent event(String report,int version,String status)throws Exception{
        var event=new ReportLifecycleEvent(UUID.randomUUID().toString(),report,1,status,version,1);
        String body=json.writeValueAsString(event);
        var operations=new com.ruanzhu.doorhandle.module.detection.repository.ReportWorkflowRepository(jdbc,json);
        var tx=new org.springframework.transaction.support.TransactionTemplate(new DataSourceTransactionManager(fixture.source()));
        tx.executeWithoutResult(txStatus->operations.workflows().create(com.ruanzhu.doorhandle.module.detection.repository.ReportWorkflowRepository.draft(
                com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowKind.REPORT_DELIVERY,"REPORT_DELIVERY",event.eventId(),
                com.ruanzhu.doorhandle.module.detection.repository.ReportWorkflowRepository.sha(body),1,1,report,version,null,"PENDING",null,
                new com.ruanzhu.doorhandle.module.detection.repository.ReportWorkflowProtocols.DeliveryV1(event.eventType(),body))));
        jdbc.update("UPDATE workflow_instance SET next_attempt_at=created_at WHERE kind='REPORT_DELIVERY' AND report_request_id=?",event.eventId());return event;
    }
    LocalDateTime now(){return LocalDateTime.now(clock);}
    ReportEventDispatcher dispatcher(ReportEventTransport transport){return new ReportEventDispatcher(repository,transport,properties,codec,clock);}
    long count(String kind){return jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind=?",Long.class,kind);}
    @Test void acknowledgedSendIsDeliveredAndReceiptDoesNotRepeat()throws Exception{
        var event=event(report,2,"SUBMITTED");var dispatcher=dispatcher((key,payload)->assertThat(inbox.receive(key,payload)).isTrue());
        assertThat(dispatcher.drain()).isEqualTo(1);assertThat(repository.get(event.eventId()).status()).isEqualTo("DELIVERED");
        assertThat(dispatcher.drain()).isZero();assertThat(count("REPORT_CONSUMPTION")).isEqualTo(1);
        assertThat(inbox.receive(report,json.writeValueAsString(event))).isFalse();
    }
    @Test void brokerFailureBackoffSurvivesDispatcherRestart()throws Exception{
        var event=event(report,2,"SUBMITTED");
        assertThat(dispatcher((key,payload)->{throw new TimeoutException("PRIVATE_PROVIDER_ERROR");}).drain()).isZero();
        assertThat(repository.get(event.eventId()).status()).isEqualTo("RETRY");assertThat(repository.get(event.eventId()).attempts()).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT error_code FROM workflow_instance WHERE kind='REPORT_DELIVERY' AND report_request_id=?",String.class,event.eventId())).isEqualTo("BROKER_UNAVAILABLE");
        var calls=new AtomicInteger();var restarted=dispatcher((key,payload)->calls.incrementAndGet());assertThat(restarted.drain()).isZero();
        clock.advance(2001);assertThat(restarted.drain()).isEqualTo(1);assertThat(calls).hasValue(1);assertThat(repository.get(event.eventId()).attempts()).isEqualTo(2);
    }
    @Test void uncertainAcknowledgementReplaysWithoutDuplicateBusinessReceipt()throws Exception{
        event(report,2,"SUBMITTED");var calls=new AtomicInteger();
        var dispatcher=dispatcher((key,payload)->{inbox.receive(key,payload);if(calls.getAndIncrement()==0)throw new TimeoutException();});
        assertThat(dispatcher.drain()).isZero();assertThat(count("REPORT_CONSUMPTION")).isEqualTo(1);
        clock.advance(2001);assertThat(dispatcher.drain()).isEqualTo(1);assertThat(calls).hasValue(2);assertThat(count("REPORT_CONSUMPTION")).isEqualTo(1);
    }
    @Test void crashedLeaseIsRecoveredAndOldTokenCannotCompleteNewAttempt()throws Exception{
        var event=event(report,2,"SUBMITTED");var row=repository.get(event.eventId());var old=repository.claim(row,now(),now().plusSeconds(60));assertThat(old).isNotNull();
        assertThat(dispatcher((k,p)->{}).drain()).isZero();clock.advance(60001);
        var resumed=repository.due(now(),20).get(0);var newer=repository.claim(resumed,now(),now().plusSeconds(60));assertThat(newer).isNotNull();
        assertThat(repository.delivered(event.eventId(),old.leaseToken(),now())).isFalse();assertThat(repository.failed(event.eventId(),old.leaseToken(),"FAILED",false,now())).isFalse();
        assertThat(repository.delivered(event.eventId(),newer.leaseToken(),now())).isTrue();
    }
    @Test void expiredLeaseCannotAcknowledgeOrRetryEvenBeforeAnotherWorkerReclaims()throws Exception{
        var event=event(report,2,"SUBMITTED");var claimed=repository.claim(repository.get(event.eventId()),now(),now().plusSeconds(60));
        assertThat(claimed).isNotNull();clock.advance(60001);
        assertThat(repository.delivered(event.eventId(),claimed.leaseToken(),now())).isFalse();
        assertThat(repository.failed(event.eventId(),claimed.leaseToken(),"BROKER_UNAVAILABLE",false,now())).isFalse();
        assertThat(repository.get(event.eventId()).status()).isEqualTo("PROCESSING");
        assertThat(repository.get(event.eventId()).attempts()).isEqualTo(1);
    }
    @Test void fastApplicationClockCannotClaimBeforeDatabaseDeadline()throws Exception{
        var event=event(report,2,"SUBMITTED");
        jdbc.update("UPDATE workflow_instance SET next_attempt_at=DATE_ADD(UTC_TIMESTAMP(6),INTERVAL 1 HOUR) WHERE kind='REPORT_DELIVERY' AND report_request_id=?",event.eventId());
        var future=now().plusHours(2);var candidate=repository.due(future,20).get(0);
        assertThat(repository.claim(candidate,future,future.plusSeconds(60))).isNull();
        assertThat(repository.get(event.eventId()).attempts()).isZero();
    }
    @Test void differentEventAtTheSameReportVersionCannotBecomeASecondReceipt()throws Exception{
        var first=event(report,2,"SUBMITTED");var conflicting=event(report,2,"WITHDRAWN");
        assertThat(inbox.receive(report,json.writeValueAsString(first))).isTrue();
        assertThatThrownBy(()->inbox.receive(report,json.writeValueAsString(conflicting))).isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        assertThat(count("REPORT_CONSUMPTION")).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT current_ref FROM runtime_state WHERE namespace='REPORT_EVENT_STATE' AND scope_key=?",String.class,report)).isEqualTo(first.eventId());
    }
    @Test void consumedAndDeliveredUtcTimestampsAreConvertedOnlyForReportDisplay()throws Exception{
        var event=event(report,2,"SUBMITTED");assertThat(dispatcher((key,body)->inbox.receive(key,body)).drain()).isEqualTo(1);
        var view=new com.ruanzhu.doorhandle.module.detection.repository.ReportWorkflowRepository(jdbc,json).events(report).get(0);
        var delivered=jdbc.queryForObject("SELECT finished_at FROM workflow_instance WHERE kind='REPORT_DELIVERY' AND report_request_id=?",LocalDateTime.class,event.eventId());
        var consumed=jdbc.queryForObject("SELECT finished_at FROM workflow_instance WHERE kind='REPORT_CONSUMPTION' AND report_request_id=?",LocalDateTime.class,event.eventId());
        assertThat(view.deliveredAt()).isEqualTo(delivered.plusHours(8));assertThat(view.consumedAt()).isEqualTo(consumed.plusHours(8));
    }
    @Test void concurrentDispatchersCannotClaimSameLiveAttempt()throws Exception{
        event(report,2,"SUBMITTED");var entered=new CountDownLatch(1);var release=new CountDownLatch(1);var calls=new AtomicInteger();
        var first=dispatcher((k,p)->{calls.incrementAndGet();entered.countDown();assertThat(release.await(5,TimeUnit.SECONDS)).isTrue();});
        var executor=Executors.newSingleThreadExecutor();try{
            var sending=executor.submit(first::drain);assertThat(entered.await(5,TimeUnit.SECONDS)).isTrue();
            assertThat(dispatcher((k,p)->calls.incrementAndGet()).drain()).isZero();release.countDown();assertThat(sending.get(5,TimeUnit.SECONDS)).isEqualTo(1);assertThat(calls).hasValue(1);
        }finally{release.countDown();executor.shutdownNow();}
    }
    @Test void newerReportEventWaitsForEarlierDeliveryAndLateReceiptCannotRegressState()throws Exception{
        var submitted=event(report,2,"SUBMITTED");var approved=event(report,3,"APPROVED");
        jdbc.update("UPDATE workflow_instance SET next_attempt_at=? WHERE kind='REPORT_DELIVERY' AND report_request_id=?",now().plusSeconds(60),submitted.eventId());
        assertThat(dispatcher((k,p)->{}).drain()).isZero();assertThat(repository.get(approved.eventId()).attempts()).isZero();
        assertThat(inbox.receive(report,json.writeValueAsString(approved))).isTrue();assertThat(inbox.receive(report,json.writeValueAsString(submitted))).isTrue();
        assertThat(jdbc.queryForObject("SELECT state_code FROM runtime_state WHERE namespace='REPORT_EVENT_STATE' AND owner_id=0 AND scope_key=?",String.class,report)).isEqualTo("APPROVED");
        clock.advance(60001);var sent=new ArrayList<String>();var sender=dispatcher((k,p)->sent.add(codec.decode(p).status()));sender.drain();clock.advance(5001);sender.drain();
        assertThat(sent).containsExactly("SUBMITTED","APPROVED");
    }
    @Test void malformedEventIsIsolatedWithoutPublishingAndBlocksOnlyItsReport()throws Exception{
        var bad=event(report,2,"SUBMITTED");event(report,3,"APPROVED");var good=event("qr-"+UUID.randomUUID(),2,"SUBMITTED");
        jdbc.update("UPDATE workflow_instance SET payload_json=JSON_SET(payload_json,'$.eventJson','PRIVATE_INVALID_JSON') WHERE kind='REPORT_DELIVERY' AND report_request_id=?",bad.eventId());
        var sent=new ArrayList<String>();dispatcher((k,p)->sent.add(codec.decode(p).eventId())).drain();
        assertThat(repository.get(bad.eventId()).status()).isEqualTo("FAILED");assertThat(sent).containsExactly(good.eventId());
    }
    @Test void receiptAndProjectionFailureRollBackTogether()throws Exception{
        var event=event(report,2,"SUBMITTED");jdbc.execute("ALTER TABLE runtime_state ADD CONSTRAINT fail_projection CHECK(namespace<>'REPORT_EVENT_STATE' OR state_code<>'SUBMITTED')");
        assertThatThrownBy(()->inbox.receive(report,json.writeValueAsString(event))).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(count("REPORT_CONSUMPTION")).isZero();
    }
    @Test void forgedPayloadKeyAndUnsupportedSchemaAreRejectedWithoutReceipt()throws Exception{
        var event=event(report,2,"SUBMITTED");String payload=json.writeValueAsString(event);
        assertThatThrownBy(()->inbox.receive("other-report",payload)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(()->inbox.receive(report,payload.replace("SUBMITTED","APPROVED"))).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(()->codec.decode(payload.replace("\"schemaVersion\":1","\"schemaVersion\":2"))).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(()->codec.decode(payload.substring(0,payload.length()-1)+",\"private\":\"secret\"}")).isInstanceOf(IllegalArgumentException.class);
        assertThat(count("REPORT_CONSUMPTION")).isZero();
    }
    @Test void databaseConfirmationFailureLeavesRecoverableLease()throws Exception{
        var event=event(report,2,"SUBMITTED");
        var failing=new ReportEventRepository(jdbc){@Override public boolean delivered(String id,String token,LocalDateTime time){throw new IllegalStateException("DB unavailable");}};
        var sender=new ReportEventDispatcher(failing,(key,payload)->inbox.receive(key,payload),properties,codec,clock);
        assertThatThrownBy(sender::drain).isInstanceOf(IllegalStateException.class);assertThat(repository.get(event.eventId()).status()).isEqualTo("PROCESSING");
        clock.advance(60001);assertThat(dispatcher((key,payload)->inbox.receive(key,payload)).drain()).isEqualTo(1);assertThat(count("REPORT_CONSUMPTION")).isEqualTo(1);
    }
    /** Advance persisted deadlines without sleeping or replacing the database's authoritative UTC clock. */
    static class MutableClock extends Clock {
        private final JdbcTemplate jdbc;
        MutableClock(JdbcTemplate jdbc){this.jdbc=jdbc;}
        void advance(long millis){
            jdbc.update("UPDATE workflow_instance SET next_attempt_at=DATE_SUB(next_attempt_at,INTERVAL ? MICROSECOND),lease_expires_at=DATE_SUB(lease_expires_at,INTERVAL ? MICROSECOND) WHERE kind='REPORT_DELIVERY'",millis*1000,millis*1000);
        }
        public ZoneId getZone(){return ZoneOffset.UTC;}public Clock withZone(ZoneId zone){return Clock.system(zone);}public Instant instant(){return Instant.now();}
    }
}
