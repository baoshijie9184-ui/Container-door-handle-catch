package com.ruanzhu.doorhandle.module.detection.service.detection;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.config.properties.KafkaTaskProperties;
import com.ruanzhu.doorhandle.contracts.detection.DetectionTaskCreatedEvent;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.kafka.KafkaException;
import org.springframework.kafka.core.KafkaTemplate;

import java.util.concurrent.CompletableFuture;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class DetectionTaskEventPublisherTest {

    @Mock
    private KafkaTemplate<String, DetectionTaskCreatedEvent> kafkaTemplate;

    @Mock
    private KafkaTaskProperties properties;

    @Test
    void publishesCreatedEventUsingTaskIdAsKey() {
        DetectionTaskEventPublisher publisher = new DetectionTaskEventPublisher(
                kafkaTemplate,
                properties,
                new ObjectMapper()
        );
        KafkaTaskProperties.Topics topics = new KafkaTaskProperties.Topics();
        topics.setTaskCreated("detection.task.created");
        when(properties.isEnabled()).thenReturn(true);
        when(properties.getTopics()).thenReturn(topics);

        DetectionTaskCreatedEvent event = DetectionTaskCreatedEvent.builder()
                .taskId("det_123")
                .build();
        when(kafkaTemplate.send("detection.task.created", "det_123", event))
                .thenReturn(CompletableFuture.completedFuture(null));

        publisher.publishCreated(event);

        verify(kafkaTemplate).send("detection.task.created", "det_123", event);
    }

    @Test
    void reportsBrokerFailureToTheDispatchService() {
        DetectionTaskEventPublisher publisher = new DetectionTaskEventPublisher(
                kafkaTemplate,
                properties,
                new ObjectMapper()
        );
        KafkaTaskProperties.Topics topics = new KafkaTaskProperties.Topics();
        topics.setTaskCreated("detection.task.created");
        when(properties.isEnabled()).thenReturn(true);
        when(properties.getTopics()).thenReturn(topics);

        DetectionTaskCreatedEvent event = DetectionTaskCreatedEvent.builder()
                .taskId("det_failed")
                .build();
        when(kafkaTemplate.send("detection.task.created", "det_failed", event))
                .thenReturn(CompletableFuture.failedFuture(new IllegalStateException("broker unavailable")));

        BusinessException error = assertThrows(
                BusinessException.class,
                () -> publisher.publishCreated(event)
        );

        assertTrue(error.getMessage().contains("Kafka 任务发送失败"));
    }

    @Test
    void normalizesSynchronousKafkaSendFailure() {
        DetectionTaskEventPublisher publisher = new DetectionTaskEventPublisher(
                kafkaTemplate,
                properties,
                new ObjectMapper()
        );
        KafkaTaskProperties.Topics topics = new KafkaTaskProperties.Topics();
        topics.setTaskCreated("detection.task.created");
        when(properties.isEnabled()).thenReturn(true);
        when(properties.getTopics()).thenReturn(topics);

        DetectionTaskCreatedEvent event = DetectionTaskCreatedEvent.builder()
                .taskId("det_sync_failed")
                .build();
        when(kafkaTemplate.send("detection.task.created", "det_sync_failed", event))
                .thenThrow(new KafkaException("Send failed"));

        BusinessException error = assertThrows(
                BusinessException.class,
                () -> publisher.publishCreated(event)
        );

        assertTrue(error.getMessage().contains("Kafka 任务发送失败"));
    }
}
