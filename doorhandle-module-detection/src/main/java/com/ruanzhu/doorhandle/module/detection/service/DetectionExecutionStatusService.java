package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.config.properties.DetectionWorkerProperties;
import com.ruanzhu.doorhandle.module.detection.config.properties.KafkaTaskProperties;
import com.ruanzhu.doorhandle.module.infra.service.OssStorageService;
import org.springframework.stereotype.Service;
import java.time.Instant;

@Service
public class DetectionExecutionStatusService {
    public record Status(boolean submitAvailable, boolean storageConfigured, boolean workerConnected,
                         String code, String message, Instant checkedAt) {}
    private final OssStorageService storage;
    private final KafkaTaskProperties kafka;
    private final DetectionWorkerProperties worker;
    private final DetectionWorkerProbe probe;
    public DetectionExecutionStatusService(OssStorageService storage, KafkaTaskProperties kafka,
            DetectionWorkerProperties worker, DetectionWorkerProbe probe) {
        this.storage=storage; this.kafka=kafka; this.worker=worker; this.probe=probe;
    }
    public Status current() {
        boolean configured = storage.isConfigured();
        if (!configured) return status(false, false, false, "STORAGE_UNCONFIGURED", "图片存储未配置，暂不能上传检测");
        if (!kafka.isEnabled()) return status(false, true, false, "KAFKA_DISABLED", "检测任务调度未启用");
        if (!worker.isEnabled()) return status(false, true, false, "WORKER_DISABLED", "检测执行服务未启用");
        try {
            if (!probe.hasConsumer(worker.getConsumerGroup(), kafka.getTopics().getTaskCreated()))
                return status(false, true, false, "WORKER_OFFLINE", "检测执行服务未接入，请启动 Worker 后刷新状态");
            return status(true, true, true, "CONNECTED", "检测执行服务已接入；任务结果以实际推理为准");
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            return status(false, true, false, "PROBE_UNAVAILABLE", "检测执行状态暂不可确认，请稍后刷新");
        } catch (Exception error) {
            return status(false, true, false, "PROBE_UNAVAILABLE", "检测调度服务不可达或状态查询失败，请检查服务后刷新");
        }
    }
    public void requireAvailable() {
        var status = current();
        if (!status.submitAvailable()) throw new BusinessException(503, status.message());
    }
    private static Status status(boolean available, boolean storage, boolean connected, String code, String message) {
        return new Status(available, storage, connected, code, message, Instant.now());
    }
}
