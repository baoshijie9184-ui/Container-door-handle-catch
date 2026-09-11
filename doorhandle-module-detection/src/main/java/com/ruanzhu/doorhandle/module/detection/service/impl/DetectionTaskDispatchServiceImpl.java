package com.ruanzhu.doorhandle.module.detection.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.detection.DetectionTaskCreatedEvent;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.service.DetectionTaskDispatchService;
import com.ruanzhu.doorhandle.module.detection.service.detection.DetectionTaskEventPublisher;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.annotation.Lazy;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;

@Service
@Slf4j
public class DetectionTaskDispatchServiceImpl implements DetectionTaskDispatchService {

    private final DetectionTaskMapper detectionTaskMapper;
    private final DetectionTaskServiceImpl detectionTaskService;
    private final DetectionTaskEventPublisher detectionTaskEventPublisher;

    public DetectionTaskDispatchServiceImpl(
            DetectionTaskMapper detectionTaskMapper,
            @Lazy DetectionTaskServiceImpl detectionTaskService,
            DetectionTaskEventPublisher detectionTaskEventPublisher
    ) {
        this.detectionTaskMapper = detectionTaskMapper;
        this.detectionTaskService = detectionTaskService;
        this.detectionTaskEventPublisher = detectionTaskEventPublisher;
    }

    @Override
    @Async
    public void dispatchTaskAsync(String taskId) {
        DetectionTask task = getTask(taskId);
        try {
            task.setStatus("QUEUED");
            task.setStage("QUEUED");
            task.setUpdatedAt(LocalDateTime.now());
            detectionTaskMapper.updateById(task);

            DetectionTaskCreatedEvent event = detectionTaskService.buildCreatedEvent(task);
            detectionTaskEventPublisher.publishCreated(event);
        } catch (Exception ex) {
            log.error("远程检测任务执行失败: {}", taskId, ex);
            detectionTaskService.failTask(taskId, ex.getMessage());
        }
    }

    private DetectionTask getTask(String taskId) {
        DetectionTask task = detectionTaskMapper.selectOne(new LambdaQueryWrapper<DetectionTask>()
                .eq(DetectionTask::getTaskId, taskId)
                .last("limit 1"));
        if (task == null) {
            throw new BusinessException("检测任务不存在: " + taskId);
        }
        return task;
    }
}
