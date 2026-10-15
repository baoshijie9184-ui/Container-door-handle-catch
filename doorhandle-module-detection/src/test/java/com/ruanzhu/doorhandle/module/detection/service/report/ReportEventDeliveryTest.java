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

class ReportEventDeliveryTest {
    JdbcTemplate jdbc;ReportEventRepository repository;ReportEventCodec codec;ReportEventInbox inbox;ReportEventProperties properties;
    MutableClock clock;ObjectMapper json=new ObjectMapper();String report;
    @BeforeEach void setup()throws Exception{
        var data=new DriverManagerDataSource("jdbc:h2:mem:event"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1","sa","");jdbc=new JdbcTemplate(data);
        for(String name:List.of("migration-V21-quality-report-approval.sql","migration-V30-report-event-delivery.sql")){
            String sql=Files.readString(Path.of("../sql/mysql",name)).replaceAll("(?m)\\) ENGINE=InnoDB[^;]*;", ");");
            for(String statement:sql.split(";"))if(!statement.isBlank())jdbc.execute(statement);
        }
        repository=new ReportEventRepository(jdbc);codec=new ReportEventCodec(json);inbox=new ReportEventInbox(jdbc,repository,codec,new DataSourceTransactionManager(data));
        properties=new ReportEventProperties();clock=new MutableClock();report="qr-"+UUID.randomUUID();
    }
    ReportLifecycleEvent event(String report,int version,String status)throws Exception{
        var event=new ReportLifecycleEvent(UUID.randomUUID().toString(),report,1,status,version,1);
        jdbc.update("INSERT INTO detection_report_outbox(event_id,report_id,event_type,payload_json,created_at,next_attempt_at) VALUES(?,?,?,?,?,?)",event.eventId(),report,event.eventType(),json.writeValueAsString(event),now(),now());return event;
    }
    LocalDateTime now(){return LocalDateTime.now(clock);}
    ReportEventDispatcher dispatcher(ReportEventTransport transport){return new ReportEventDispatcher(repository,transport,properties,codec,clock);}
    long count(String table){return jdbc.queryForObject("SELECT COUNT(*) FROM "+table,Long.class);}
    @Test void acknowledgedSendIsDeliveredAndReceiptDoesNotRepeat()throws Exception{
        var event=event(report,2,"SUBMITTED");var dispatcher=dispatcher((key,payload)->assertThat(inbox.receive(key,payload)).isTrue());
        assertThat(dispatcher.drain()).isEqualTo(1);assertThat(repository.get(event.eventId()).status()).isEqualTo("DELIVERED");
        assertThat(dispatcher.drain()).isZero();assertThat(count("detection_report_event_receipt")).isEqualTo(1);
        assertThat(inbox.receive(report,json.writeValueAsString(event))).isFalse();
    }
    @Test void brokerFailureBackoffSurvivesDispatcherRestart()throws Exception{
        var event=event(report,2,"SUBMITTED");
        assertThat(dispatcher((key,payload)->{throw new TimeoutException("PRIVATE_PROVIDER_ERROR");}).drain()).isZero();
        assertThat(repository.get(event.eventId()).status()).isEqualTo("RETRY");assertThat(repository.get(event.eventId()).attempts()).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT last_error_code FROM detection_report_outbox WHERE event_id=?",String.class,event.eventId())).isEqualTo("BROKER_UNAVAILABLE");
        var calls=new AtomicInteger();var restarted=dispatcher((key,payload)->calls.incrementAndGet());assertThat(restarted.drain()).isZero();
        clock.advance(2001);assertThat(restarted.drain()).isEqualTo(1);assertThat(calls).hasValue(1);assertThat(repository.get(event.eventId()).attempts()).isEqualTo(2);
    }
    @Test void uncertainAcknowledgementReplaysWithoutDuplicateBusinessReceipt()throws Exception{
        event(report,2,"SUBMITTED");var calls=new AtomicInteger();
        var dispatcher=dispatcher((key,payload)->{inbox.receive(key,payload);if(calls.getAndIncrement()==0)throw new TimeoutException();});
        assertThat(dispatcher.drain()).isZero();assertThat(count("detection_report_event_receipt")).isEqualTo(1);
        clock.advance(2001);assertThat(dispatcher.drain()).isEqualTo(1);assertThat(calls).hasValue(2);assertThat(count("detection_report_event_receipt")).isEqualTo(1);
    }
    @Test void crashedLeaseIsRecoveredAndOldTokenCannotCompleteNewAttempt()throws Exception{
        var event=event(report,2,"SUBMITTED");var row=repository.get(event.eventId());assertThat(repository.claim(row,"old-token",now(),now().plusSeconds(60))).isTrue();
        assertThat(dispatcher((k,p)->{}).drain()).isZero();clock.advance(60001);
        var resumed=repository.due(now(),20).get(0);assertThat(repository.claim(resumed,"new-token",now(),now().plusSeconds(60))).isTrue();
        assertThat(repository.delivered(event.eventId(),"old-token",now())).isFalse();assertThat(repository.failed(event.eventId(),"old-token","FAILED",false,now())).isFalse();
        assertThat(repository.delivered(event.eventId(),"new-token",now())).isTrue();
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
        jdbc.update("UPDATE detection_report_outbox SET next_attempt_at=? WHERE event_id=?",now().plusSeconds(60),submitted.eventId());
        assertThat(dispatcher((k,p)->{}).drain()).isZero();assertThat(repository.get(approved.eventId()).attempts()).isZero();
        assertThat(inbox.receive(report,json.writeValueAsString(approved))).isTrue();assertThat(inbox.receive(report,json.writeValueAsString(submitted))).isTrue();
        assertThat(jdbc.queryForObject("SELECT status FROM detection_report_event_state WHERE report_id=?",String.class,report)).isEqualTo("APPROVED");
        clock.advance(60001);var sent=new ArrayList<String>();var sender=dispatcher((k,p)->sent.add(codec.decode(p).status()));sender.drain();clock.advance(5001);sender.drain();
        assertThat(sent).containsExactly("SUBMITTED","APPROVED");
    }
    @Test void malformedEventIsIsolatedWithoutPublishingAndBlocksOnlyItsReport()throws Exception{
        var bad=event(report,2,"SUBMITTED");event(report,3,"APPROVED");var good=event("qr-"+UUID.randomUUID(),2,"SUBMITTED");
        jdbc.update("UPDATE detection_report_outbox SET payload_json='PRIVATE_INVALID_JSON' WHERE event_id=?",bad.eventId());
        var sent=new ArrayList<String>();dispatcher((k,p)->sent.add(codec.decode(p).eventId())).drain();
        assertThat(repository.get(bad.eventId()).status()).isEqualTo("FAILED");assertThat(sent).containsExactly(good.eventId());
    }
    @Test void receiptAndProjectionFailureRollBackTogether()throws Exception{
        var event=event(report,2,"SUBMITTED");jdbc.execute("ALTER TABLE detection_report_event_state ADD CONSTRAINT fail_projection CHECK(status<>'SUBMITTED')");
        assertThatThrownBy(()->inbox.receive(report,json.writeValueAsString(event))).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(count("detection_report_event_receipt")).isZero();
    }
    @Test void forgedPayloadKeyAndUnsupportedSchemaAreRejectedWithoutReceipt()throws Exception{
        var event=event(report,2,"SUBMITTED");String payload=json.writeValueAsString(event);
        assertThatThrownBy(()->inbox.receive("other-report",payload)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(()->inbox.receive(report,payload.replace("SUBMITTED","APPROVED"))).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(()->codec.decode(payload.replace("\"schemaVersion\":1","\"schemaVersion\":2"))).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(()->codec.decode(payload.substring(0,payload.length()-1)+",\"private\":\"secret\"}")).isInstanceOf(IllegalArgumentException.class);
        assertThat(count("detection_report_event_receipt")).isZero();
    }
    @Test void databaseConfirmationFailureLeavesRecoverableLease()throws Exception{
        var event=event(report,2,"SUBMITTED");
        var failing=new ReportEventRepository(jdbc){@Override public boolean delivered(String id,String token,LocalDateTime time){throw new IllegalStateException("DB unavailable");}};
        var sender=new ReportEventDispatcher(failing,(key,payload)->inbox.receive(key,payload),properties,codec,clock);
        assertThatThrownBy(sender::drain).isInstanceOf(IllegalStateException.class);assertThat(repository.get(event.eventId()).status()).isEqualTo("PROCESSING");
        clock.advance(60001);assertThat(dispatcher((key,payload)->inbox.receive(key,payload)).drain()).isEqualTo(1);assertThat(count("detection_report_event_receipt")).isEqualTo(1);
    }
    static class MutableClock extends Clock {
        private Instant instant=Instant.parse("2026-10-14T08:00:00Z");
        void advance(long millis){instant=instant.plusMillis(millis);}
        public ZoneId getZone(){return ZoneId.of("Asia/Shanghai");}public Clock withZone(ZoneId zone){return this;}public Instant instant(){return instant;}
    }
}
