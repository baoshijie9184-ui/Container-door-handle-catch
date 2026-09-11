package com.ruanzhu.doorhandle.module.detection.service.detection;

import com.ruanzhu.doorhandle.contracts.detection.DetectionTaskFinishedEvent;
import com.ruanzhu.doorhandle.module.detection.service.impl.DetectionTaskServiceImpl;
import lombok.RequiredArgsConstructor;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class DetectionTaskFinishedEventListener {

    private final DetectionTaskServiceImpl detectionTaskService;

    @KafkaListener(
            topics = "#{@kafkaTaskProperties.topics.taskFinished}",
            groupId = "#{@kafkaTaskProperties.consumerGroup}",
            containerFactory = "detectionTaskFinishedKafkaListenerContainerFactory"
    )
    public void onFinished(DetectionTaskFinishedEvent event) {
        detectionTaskService.applyFinishedEvent(event);
    }
}
