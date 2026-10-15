package com.ruanzhu.doorhandle.module.detection.config;

import com.ruanzhu.doorhandle.module.detection.config.properties.*;
import com.ruanzhu.doorhandle.module.detection.service.report.ReportEventTransport;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.common.serialization.*;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.*;
import org.springframework.kafka.config.ConcurrentKafkaListenerContainerFactory;
import org.springframework.kafka.core.*;
import org.springframework.kafka.listener.*;
import org.springframework.util.backoff.FixedBackOff;
import java.time.Clock;
import java.util.*;
import java.util.concurrent.TimeUnit;

@Configuration
@ConditionalOnProperty(prefix="app.report-events",name="enabled",havingValue="true")
public class ReportEventConfiguration {
    @Bean public Clock reportEventClock(){return Clock.systemDefaultZone();}
    @Bean public ProducerFactory<String,String> reportEventProducerFactory(KafkaTaskProperties kafka,ReportEventProperties settings){
        if(!kafka.isEnabled())throw new IllegalStateException("Report events require app.kafka.enabled=true");
        Map<String,Object> config=new HashMap<>();
        config.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG,kafka.getBootstrapServers());
        config.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG,StringSerializer.class);config.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG,StringSerializer.class);
        config.put(ProducerConfig.ACKS_CONFIG,"all");config.put(ProducerConfig.ENABLE_IDEMPOTENCE_CONFIG,true);
        config.put(ProducerConfig.MAX_BLOCK_MS_CONFIG,settings.getSendTimeoutMs());
        config.put(ProducerConfig.DELIVERY_TIMEOUT_MS_CONFIG,(int)settings.getSendTimeoutMs());
        config.put(ProducerConfig.REQUEST_TIMEOUT_MS_CONFIG,(int)settings.getSendTimeoutMs());
        config.put(ProducerConfig.LINGER_MS_CONFIG,0);
        return new DefaultKafkaProducerFactory<>(config);
    }
    @Bean public KafkaTemplate<String,String> reportEventKafkaTemplate(@Qualifier("reportEventProducerFactory")ProducerFactory<String,String> factory){return new KafkaTemplate<>(factory);}
    @Bean public ReportEventTransport reportEventTransport(@Qualifier("reportEventKafkaTemplate")KafkaTemplate<String,String> kafka,ReportEventProperties settings){
        return (reportId,payload)->kafka.send(settings.getTopic(),reportId,payload).get(settings.getSendTimeoutMs(),TimeUnit.MILLISECONDS);
    }
    @Bean public ConcurrentKafkaListenerContainerFactory<String,String> reportEventListenerFactory(KafkaTaskProperties kafka,ReportEventProperties settings){
        Map<String,Object> config=new HashMap<>();config.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG,kafka.getBootstrapServers());
        config.put(ConsumerConfig.GROUP_ID_CONFIG,settings.getConsumerGroup());config.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG,false);
        config.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG,"earliest");config.put(ConsumerConfig.MAX_POLL_RECORDS_CONFIG,10);
        var factory=new ConcurrentKafkaListenerContainerFactory<String,String>();
        factory.setConsumerFactory(new DefaultKafkaConsumerFactory<>(config,new StringDeserializer(),new StringDeserializer()));
        factory.getContainerProperties().setAckMode(ContainerProperties.AckMode.RECORD);
        var errors=new DefaultErrorHandler(new FixedBackOff(2000,FixedBackOff.UNLIMITED_ATTEMPTS));
        errors.setClassifications(Map.of(Exception.class,true),true);factory.setCommonErrorHandler(errors);
        return factory;
    }
}
