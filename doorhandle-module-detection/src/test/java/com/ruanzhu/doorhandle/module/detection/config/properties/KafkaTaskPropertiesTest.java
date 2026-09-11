package com.ruanzhu.doorhandle.module.detection.config.properties;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Configuration;
import org.springframework.test.context.TestPropertySource;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

@SpringBootTest(classes = KafkaTaskPropertiesTest.TestConfig.class)
@TestPropertySource(properties = {
        "app.kafka.enabled=true",
        "app.kafka.bootstrap-servers=localhost:9092",
        "app.kafka.send-timeout-ms=5000",
        "app.kafka.topics.task-created=detection.task.created",
        "app.kafka.topics.task-finished=detection.task.finished",
        "app.kafka.consumer-group=detection-java"
})
class KafkaTaskPropertiesTest {

    @Configuration
    @EnableConfigurationProperties(KafkaTaskProperties.class)
    static class TestConfig {
    }

    @Autowired
    private KafkaTaskProperties properties;

    @Test
    void bindsKafkaTaskProperties() {
        assertTrue(properties.isEnabled());
        assertEquals("localhost:9092", properties.getBootstrapServers());
        assertEquals(5000L, properties.getSendTimeoutMs());
        assertEquals("detection.task.created", properties.getTopics().getTaskCreated());
        assertEquals("detection.task.finished", properties.getTopics().getTaskFinished());
        assertEquals("detection-java", properties.getConsumerGroup());
    }
}
