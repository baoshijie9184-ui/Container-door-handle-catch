package com.ruanzhu.doorhandle.server;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.detection.ReportLifecycleEvent;
import com.ruanzhu.doorhandle.module.detection.config.ReportEventConfiguration;
import com.ruanzhu.doorhandle.module.detection.config.properties.*;
import com.ruanzhu.doorhandle.module.detection.repository.ReportEventRepository;
import com.ruanzhu.doorhandle.module.detection.service.report.*;
import io.github.cdimascio.dotenv.Dotenv;
import org.apache.kafka.clients.admin.*;
import org.apache.kafka.clients.consumer.*;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.kafka.core.*;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import static org.assertj.core.api.Assertions.*;

/** 实际 MySQL 与 Kafka。仅创建验收事件，不修改真实任务、报告或审批状态。 */
@EnabledIfSystemProperty(named="report.events.local.mysql",matches="true")
class ReportEventLocalMysqlTest {
    @Test void retriesSurviveRestartAndActualKafkaReceiptsAreIdempotentAndMonotonic()throws Exception{
        Path root=Path.of("..").toAbsolutePath().normalize();var env=Dotenv.configure().directory(root.toString()).load();
        String bootstrap=env.get("APP_KAFKA_BOOTSTRAP_SERVERS","127.0.0.1:9092");
        if(!Set.of("localhost:9092","127.0.0.1:9092").contains(bootstrap))throw new IllegalStateException("Only local Kafka allowed");
        try(var context=new AnnotationConfigApplicationContext(AgentCardsLocalMysqlTest.Config.class)){
            var jdbc=context.getBean(JdbcTemplate.class);var json=context.getBean(ObjectMapper.class);var codec=new ReportEventCodec(json);
            String report="qr-"+UUID.randomUUID();
            var first=new ReportLifecycleEvent(UUID.randomUUID().toString(),report,1,"SUBMITTED",2,1);
            var last=new ReportLifecycleEvent(UUID.randomUUID().toString(),report,1,"APPROVED",3,1);
            for(var event:List.of(first,last))jdbc.update("INSERT INTO detection_report_outbox(event_id,report_id,event_type,payload_json,created_at,next_attempt_at) VALUES(?,?,?,?,NOW(),NOW())",event.eventId(),report,event.eventType(),json.writeValueAsString(event));
            var repository=new ReportEventRepository(jdbc){@Override public List<Entry> due(LocalDateTime time,int limit){return super.due(time,1000).stream().filter(entry->entry.reportId().equals(report)).toList();}};
            var settings=new ReportEventProperties();settings.setTopic("doorhandle.report.delivery.acceptance.v1");settings.setSendTimeoutMs(5000);
            var now=new AtomicReference<>(Instant.now());Clock clock=new Clock(){public ZoneId getZone(){return ZoneId.systemDefault();}public Clock withZone(ZoneId zone){return this;}public Instant instant(){return now.get();}};
            var offline=new ReportEventDispatcher(repository,(key,payload)->{throw new java.util.concurrent.TimeoutException();},settings,codec,clock);
            assertThat(offline.drain()).isZero();assertThat(repository.get(first.eventId()).status()).isEqualTo("RETRY");now.set(now.get().plusSeconds(6));
            var kafka=new KafkaTaskProperties();kafka.setEnabled(true);kafka.setBootstrapServers(bootstrap);var config=new ReportEventConfiguration();
            try(var admin=AdminClient.create(Map.of("bootstrap.servers",bootstrap))){
                if(!admin.listTopics().names().get(10,TimeUnit.SECONDS).contains(settings.getTopic()))admin.createTopics(List.of(new NewTopic(settings.getTopic(),1,(short)1).configs(Map.of("retention.ms","86400000")))).all().get(10,TimeUnit.SECONDS);
            }
            var producer=(DefaultKafkaProducerFactory<String,String>)config.reportEventProducerFactory(kafka,settings);
            var template=new KafkaTemplate<>(producer);
            try{
                var resumed=new ReportEventDispatcher(repository,config.reportEventTransport(template,settings),settings,codec,clock);
                assertThat(resumed.drain()).isEqualTo(2);assertThat(repository.get(last.eventId()).status()).isEqualTo("DELIVERED");
                template.send(settings.getTopic(),report,json.writeValueAsString(first)).get(10,TimeUnit.SECONDS);
                Map<String,Object> options=new HashMap<>();options.put("bootstrap.servers",bootstrap);options.put("group.id","report-verify-"+UUID.randomUUID());options.put("auto.offset.reset","earliest");options.put("enable.auto.commit",false);
                var messages=new ArrayList<ConsumerRecord<String,String>>();
                try(var consumer=new KafkaConsumer<String,String>(options,new StringDeserializer(),new StringDeserializer())){
                    consumer.subscribe(List.of(settings.getTopic()));long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(25);
                    while(messages.size()<3&&System.nanoTime()<deadline)for(var record:consumer.poll(Duration.ofMillis(500)))if(report.equals(record.key()))messages.add(record);
                }
                assertThat(messages).hasSize(3);
                var inbox=new ReportEventInbox(jdbc,repository,codec,context.getBean(DataSourceTransactionManager.class));
                // 刻意先交付较新版本，验证晚到与重复不会倒退接收端状态。
                var newest=messages.stream().filter(message->codec.decode(message.value()).version()==3).findFirst().orElseThrow();inbox.receive(newest.key(),newest.value());
                for(var message:messages)inbox.receive(message.key(),message.value());
                assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM detection_report_event_receipt WHERE report_id=?",Long.class,report)).isEqualTo(2);
                assertThat(jdbc.queryForObject("SELECT status FROM detection_report_event_state WHERE report_id=?",String.class,report)).isEqualTo("APPROVED");
                Files.writeString(root.resolve("work/report-events-local-mysql-kafka.json"),json.writerWithDefaultPrettyPrinter().writeValueAsString(Map.of("actualMysql",true,"actualKafka",true,"brokerRecords",3,"uniqueReceipts",2,"restartedRetryVerified",true,"lateVersionDidNotRegressState",true,"existingReportsChanged",false,"paidModelsCalled",false,"passed",true)));
            }finally{template.destroy();producer.destroy();}
        }
    }
}
