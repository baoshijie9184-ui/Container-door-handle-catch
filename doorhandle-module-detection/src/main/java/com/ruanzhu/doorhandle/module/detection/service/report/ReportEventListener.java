package com.ruanzhu.doorhandle.module.detection.service.report;

import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Service;

@Service
@ConditionalOnProperty(prefix="app.report-events",name="enabled",havingValue="true")
public class ReportEventListener {
    private final ReportEventInbox inbox;
    public ReportEventListener(ReportEventInbox inbox){this.inbox=inbox;}
    @KafkaListener(topics="#{@reportEventProperties.topic}",groupId="#{@reportEventProperties.consumerGroup}",containerFactory="reportEventListenerFactory")
    public void receive(ConsumerRecord<String,String> record){inbox.receive(record.key(),record.value());}
}
