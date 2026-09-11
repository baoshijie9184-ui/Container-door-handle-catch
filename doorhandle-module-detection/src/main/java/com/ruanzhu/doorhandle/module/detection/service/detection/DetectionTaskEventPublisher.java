package com.ruanzhu.doorhandle.module.detection.service.detection;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.config.properties.KafkaTaskProperties;
import com.ruanzhu.doorhandle.contracts.detection.DetectionTaskCreatedEvent;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Service;

import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

@Service
@RequiredArgsConstructor
@Slf4j
public class DetectionTaskEventPublisher {

    private final KafkaTemplate<String, DetectionTaskCreatedEvent> kafkaTemplate;
    private final KafkaTaskProperties kafkaTaskProperties;
    private final ObjectMapper objectMapper;

    public void publishCreated(DetectionTaskCreatedEvent event) {
        if (!kafkaTaskProperties.isEnabled()) {
            throw new BusinessException("Kafka 未启用，无法发送检测任务");
        }
        log.info(
                "Publishing detection.task.created event. taskId={}, payload={}",
                event.getTaskId(),
                toJsonForLog(event)
        );
        try {
            kafkaTemplate.send(
                    kafkaTaskProperties.getTopics().getTaskCreated(),
                    event.getTaskId(),
                    event
            ).get(kafkaTaskProperties.getSendTimeoutMs(), TimeUnit.MILLISECONDS);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new BusinessException("Kafka 任务发送被中断: " + event.getTaskId());
        } catch (ExecutionException | TimeoutException ex) {
            log.error("Kafka task publish failed. taskId={}", event.getTaskId(), ex);
            throw new BusinessException("Kafka 任务发送失败: " + event.getTaskId());
        } catch (RuntimeException ex) {
            log.error("Kafka task send failed before acknowledgement. taskId={}", event.getTaskId(), ex);
            throw new BusinessException("Kafka 任务发送失败: " + event.getTaskId());
        }
    }

    private String toJsonForLog(DetectionTaskCreatedEvent event) {
        try {
            return objectMapper.writeValueAsString(event);
        } catch (JsonProcessingException ex) {
            log.warn("Failed to serialize detection.task.created event for logging. taskId={}", event.getTaskId(), ex);
            return "{\"taskId\":\"" + event.getTaskId() + "\",\"serialization\":\"failed\"}";
        }
    }
}
