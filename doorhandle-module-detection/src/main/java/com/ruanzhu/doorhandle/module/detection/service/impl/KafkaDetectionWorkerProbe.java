package com.ruanzhu.doorhandle.module.detection.service.impl;

import com.ruanzhu.doorhandle.module.detection.config.properties.KafkaTaskProperties;
import com.ruanzhu.doorhandle.module.detection.service.DetectionWorkerProbe;
import org.apache.kafka.clients.admin.AdminClient;
import org.apache.kafka.clients.admin.AdminClientConfig;
import org.springframework.stereotype.Component;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

/** 只读取消费组成员及任务主题分区，不拉取或确认业务消息。 */
@Component
public class KafkaDetectionWorkerProbe implements DetectionWorkerProbe {
    private final KafkaTaskProperties kafka;
    public KafkaDetectionWorkerProbe(KafkaTaskProperties kafka) { this.kafka = kafka; }
    public boolean hasConsumer(String group, String topic) throws Exception {
        var admin = AdminClient.create(Map.of(
                AdminClientConfig.BOOTSTRAP_SERVERS_CONFIG, kafka.getBootstrapServers(),
                AdminClientConfig.REQUEST_TIMEOUT_MS_CONFIG, 1200,
                AdminClientConfig.DEFAULT_API_TIMEOUT_MS_CONFIG, 1500));
        try {
            var description = admin.describeConsumerGroups(List.of(group)).describedGroups().get(group).get(1500, TimeUnit.MILLISECONDS);
            return description.members().stream().anyMatch(member -> member.assignment().topicPartitions().stream()
                    .anyMatch(partition -> topic.equals(partition.topic())));
        } finally { admin.close(Duration.ofMillis(200)); }
    }
}
