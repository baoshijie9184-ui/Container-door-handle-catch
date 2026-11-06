package com.ruanzhu.doorhandle.server;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.detection.ReportLifecycleEvent;
import com.ruanzhu.doorhandle.module.detection.config.ReportEventConfiguration;
import com.ruanzhu.doorhandle.module.detection.config.properties.*;
import com.ruanzhu.doorhandle.module.detection.repository.ReportEventRepository;
import com.ruanzhu.doorhandle.module.detection.repository.ReportWorkflowRepository;
import com.ruanzhu.doorhandle.module.detection.repository.ReportWorkflowProtocols;
import com.ruanzhu.doorhandle.module.detection.service.report.*;
import com.ruanzhu.doorhandle.framework.persistence.workflow.WorkflowKind;
import org.apache.kafka.clients.admin.*;
import org.apache.kafka.clients.consumer.*;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.kafka.core.*;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.TimeUnit;
import static org.assertj.core.api.Assertions.*;

/** 实际 MySQL 与 Kafka。仅创建验收事件，不修改真实任务、报告或审批状态。 */
@EnabledIfSystemProperty(named="report.events.local.mysql",matches="true")
class ReportEventLocalMysqlTest {
    @Test void retriesSurviveRestartAndActualKafkaReceiptsAreIdempotentAndMonotonic()throws Exception{
        Path root=Path.of(System.getProperty("agent.report.project", "..")).toAbsolutePath().normalize();
        String bootstrap=EcsMysqlFixture.value("kafkaBootstrapServers");
        if(!bootstrap.matches("127\\.0\\.0\\.1:[0-9]{4,5}"))throw new IllegalStateException("Only the explicit ECS fixture Kafka is allowed");
        try(var context=new AnnotationConfigApplicationContext(AgentCardsLocalMysqlTest.Config.class)){
            var jdbc=context.getBean(JdbcTemplate.class);var json=context.getBean(ObjectMapper.class);var codec=new ReportEventCodec(json);
            String report="qr-"+UUID.randomUUID();
            long actor=context.getBean(com.ruanzhu.doorhandle.module.system.mapper.UserMapper.class).findByUsername("inspector.demo").getId();
            long existingReports=jdbc.queryForObject("SELECT COUNT(*) FROM quality_report",Long.class);
            var first=new ReportLifecycleEvent(UUID.randomUUID().toString(),report,actor,"SUBMITTED",2,1);
            var last=new ReportLifecycleEvent(UUID.randomUUID().toString(),report,actor,"APPROVED",3,1);
            var workflows=new ReportWorkflowRepository(jdbc,json);
            var tx=new TransactionTemplate(context.getBean(DataSourceTransactionManager.class));
            for(var event:List.of(first,last)) {
                String payload=json.writeValueAsString(event);
                tx.executeWithoutResult(status->workflows.workflows().create(ReportWorkflowRepository.draft(
                        WorkflowKind.REPORT_DELIVERY,ReportWorkflowRepository.DELIVERY_SCOPE,event.eventId(),ReportWorkflowRepository.sha(payload),
                        actor,actor,report,event.version(),null,"PENDING",null,new ReportWorkflowProtocols.DeliveryV1(event.eventType(),payload))));
            }
            var repository=ownedEvents(jdbc,report);
            var settings=new ReportEventProperties();settings.setTopic("doorhandle.report.delivery.acceptance.v1");settings.setSendTimeoutMs(5000);
            Clock clock=Clock.systemUTC();
            var offline=new ReportEventDispatcher(repository,(key,payload)->{throw new java.util.concurrent.TimeoutException();},settings,codec,clock);
            assertThat(offline.drain()).isZero();assertThat(repository.get(first.eventId()).status()).isEqualTo("RETRY");
            assertThat(repository.get(first.eventId()).attempts()).isEqualTo(1);
            // The production claim checks database UTC. Arrange only this fixture's unclaimed retries as due,
            // instead of advancing a Java-only clock while leaving the database deadline in the future.
            assertThat(jdbc.update("""
                    UPDATE workflow_instance SET next_attempt_at=CASE WHEN request_id=? THEN DATE_SUB(UTC_TIMESTAMP(6),INTERVAL 2 SECOND)
                      ELSE DATE_SUB(UTC_TIMESTAMP(6),INTERVAL 1 SECOND) END
                    WHERE kind='REPORT_DELIVERY' AND resource_type='QUALITY_REPORT' AND resource_id=?
                      AND request_id IN (?,?) AND status='RETRY' AND claim_token IS NULL
                    """,first.eventId(),report,first.eventId(),last.eventId())).isEqualTo(2);
            var kafka=new KafkaTaskProperties();kafka.setEnabled(true);kafka.setBootstrapServers(bootstrap);var config=new ReportEventConfiguration();
            try(var admin=AdminClient.create(Map.of("bootstrap.servers",bootstrap))){
                if(!admin.listTopics().names().get(10,TimeUnit.SECONDS).contains(settings.getTopic()))admin.createTopics(List.of(new NewTopic(settings.getTopic(),1,(short)1).configs(Map.of("retention.ms","86400000")))).all().get(10,TimeUnit.SECONDS);
            }
            var producer=(DefaultKafkaProducerFactory<String,String>)config.reportEventProducerFactory(kafka,settings);
            var template=new KafkaTemplate<>(producer);
            try{
                var restartedRepository=ownedEvents(jdbc,report);
                assertThat(restartedRepository.get(first.eventId()).attempts()).isEqualTo(1);
                var resumed=new ReportEventDispatcher(restartedRepository,config.reportEventTransport(template,settings),settings,codec,clock);
                assertThat(resumed.drain()).isEqualTo(2);assertThat(restartedRepository.get(last.eventId()).status()).isEqualTo("DELIVERED");
                assertThat(restartedRepository.get(first.eventId()).attempts()).isEqualTo(2);
                assertThat(restartedRepository.get(first.eventId()).leaseToken()).isNull();
                template.send(settings.getTopic(),report,json.writeValueAsString(first)).get(10,TimeUnit.SECONDS);
                Map<String,Object> options=new HashMap<>();options.put("bootstrap.servers",bootstrap);options.put("group.id","report-verify-"+UUID.randomUUID());options.put("auto.offset.reset","earliest");options.put("enable.auto.commit",false);
                var messages=new ArrayList<ConsumerRecord<String,String>>();
                try(var consumer=new KafkaConsumer<String,String>(options,new StringDeserializer(),new StringDeserializer())){
                    consumer.subscribe(List.of(settings.getTopic()));long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(25);
                    while(messages.size()<3&&System.nanoTime()<deadline)for(var record:consumer.poll(Duration.ofMillis(500)))if(report.equals(record.key()))messages.add(record);
                }
                assertThat(messages).hasSize(3);
                var inbox=new ReportEventInbox(jdbc,restartedRepository,codec,context.getBean(DataSourceTransactionManager.class));
                // 刻意先交付较新版本，验证晚到与重复不会倒退接收端状态。
                var newest=messages.stream().filter(message->codec.decode(message.value()).version()==3).findFirst().orElseThrow();assertThat(inbox.receive(newest.key(),newest.value())).isTrue();
                for(var message:messages)inbox.receive(message.key(),message.value());
                assertThat(inbox.receive(newest.key(),newest.value())).isFalse();
                assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='REPORT_CONSUMPTION' AND resource_type='QUALITY_REPORT' AND resource_id=?",Long.class,report)).isEqualTo(2);
                assertThat(jdbc.queryForMap("SELECT state_code,current_ref,counter_value FROM runtime_state WHERE namespace='REPORT_EVENT_STATE' AND owner_id=0 AND scope_key=?",report))
                        .containsEntry("state_code","APPROVED").containsEntry("current_ref",last.eventId()).containsEntry("counter_value",3L);
                assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM quality_report",Long.class)).isEqualTo(existingReports);
                Files.writeString(root.resolve("work/report-events-local-mysql-kafka.json"),json.writerWithDefaultPrettyPrinter().writeValueAsString(Map.of("actualMysql",true,"actualKafka",true,"brokerRecords",3,"uniqueReceipts",2,"restartedRetryVerified",true,"lateVersionDidNotRegressState",true,"existingReportsChanged",false,"paidModelsCalled",false,"passed",true)));
            }finally{template.destroy();producer.destroy();}
        }
    }
    private static ReportEventRepository ownedEvents(JdbcTemplate jdbc,String report) {
        return new ReportEventRepository(jdbc){@Override public List<Entry> due(LocalDateTime time,int limit){return super.due(time,1000).stream().filter(entry->entry.reportId().equals(report)).toList();}};
    }
}
