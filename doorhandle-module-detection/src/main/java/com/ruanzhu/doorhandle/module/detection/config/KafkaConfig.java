package com.ruanzhu.doorhandle.module.detection.config;

import com.ruanzhu.doorhandle.module.detection.config.properties.KafkaTaskProperties;
import com.ruanzhu.doorhandle.contracts.detection.DetectionTaskCreatedEvent;
import com.ruanzhu.doorhandle.contracts.detection.DetectionTaskFinishedEvent;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.apache.kafka.common.serialization.StringSerializer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.config.ConcurrentKafkaListenerContainerFactory;
import org.springframework.kafka.core.ConsumerFactory;
import org.springframework.kafka.core.DefaultKafkaConsumerFactory;
import org.springframework.kafka.core.DefaultKafkaProducerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.core.ProducerFactory;
import org.springframework.kafka.support.serializer.JsonDeserializer;
import org.springframework.kafka.support.serializer.JsonSerializer;

import java.util.HashMap;
import java.util.Map;

@Configuration
public class KafkaConfig {

    @Bean
    public ProducerFactory<String, DetectionTaskCreatedEvent> detectionTaskCreatedProducerFactory(
            KafkaTaskProperties kafkaTaskProperties
    ) {
        Map<String, Object> config = new HashMap<>();
        config.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, kafkaTaskProperties.getBootstrapServers());
        config.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class);
        config.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, JsonSerializer.class);
        config.put(ProducerConfig.MAX_BLOCK_MS_CONFIG, kafkaTaskProperties.getSendTimeoutMs());
        config.put(JsonSerializer.ADD_TYPE_INFO_HEADERS, false);
        return new DefaultKafkaProducerFactory<>(config);
    }

    @Bean
    public KafkaTemplate<String, DetectionTaskCreatedEvent> detectionTaskCreatedKafkaTemplate(
            ProducerFactory<String, DetectionTaskCreatedEvent> detectionTaskCreatedProducerFactory
    ) {
        return new KafkaTemplate<>(detectionTaskCreatedProducerFactory);
    }

    @Bean
    public ConsumerFactory<String, DetectionTaskFinishedEvent> detectionTaskFinishedConsumerFactory(
            KafkaTaskProperties kafkaTaskProperties
    ) {
        JsonDeserializer<DetectionTaskFinishedEvent> jsonDeserializer =
                new JsonDeserializer<>(DetectionTaskFinishedEvent.class);
        jsonDeserializer.addTrustedPackages("com.ruanzhu.doorhandle.contracts.detection");
        jsonDeserializer.setUseTypeHeaders(false);

        Map<String, Object> config = new HashMap<>();
        config.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, kafkaTaskProperties.getBootstrapServers());
        config.put(ConsumerConfig.GROUP_ID_CONFIG, kafkaTaskProperties.getConsumerGroup());
        config.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
        config.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, JsonDeserializer.class);
        config.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");

        return new DefaultKafkaConsumerFactory<>(
                config,
                new StringDeserializer(),
                jsonDeserializer
        );
    }

    @Bean
    public ConcurrentKafkaListenerContainerFactory<String, DetectionTaskFinishedEvent>
    detectionTaskFinishedKafkaListenerContainerFactory(
            ConsumerFactory<String, DetectionTaskFinishedEvent> detectionTaskFinishedConsumerFactory
    ) {
        ConcurrentKafkaListenerContainerFactory<String, DetectionTaskFinishedEvent> factory =
                new ConcurrentKafkaListenerContainerFactory<>();
        factory.setConsumerFactory(detectionTaskFinishedConsumerFactory);
        return factory;
    }
}
