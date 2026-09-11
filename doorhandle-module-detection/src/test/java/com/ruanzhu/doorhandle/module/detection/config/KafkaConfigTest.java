package com.ruanzhu.doorhandle.module.detection.config;

import com.ruanzhu.doorhandle.module.detection.config.properties.KafkaTaskProperties;
import com.ruanzhu.doorhandle.contracts.detection.DetectionTaskCreatedEvent;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.junit.jupiter.api.Test;
import org.springframework.kafka.core.DefaultKafkaProducerFactory;
import org.springframework.kafka.core.ProducerFactory;

import static org.junit.jupiter.api.Assertions.assertEquals;

class KafkaConfigTest {

    @Test
    void limitsHowLongProducerMayBlockWhileBrokerIsUnavailable() {
        KafkaTaskProperties properties = new KafkaTaskProperties();
        properties.setBootstrapServers("localhost:9092");
        properties.setSendTimeoutMs(5000L);

        ProducerFactory<String, DetectionTaskCreatedEvent> factory =
                new KafkaConfig().detectionTaskCreatedProducerFactory(properties);
        DefaultKafkaProducerFactory<String, DetectionTaskCreatedEvent> defaultFactory =
                (DefaultKafkaProducerFactory<String, DetectionTaskCreatedEvent>) factory;

        assertEquals(
                5000L,
                defaultFactory.getConfigurationProperties().get(ProducerConfig.MAX_BLOCK_MS_CONFIG)
        );
    }
}
