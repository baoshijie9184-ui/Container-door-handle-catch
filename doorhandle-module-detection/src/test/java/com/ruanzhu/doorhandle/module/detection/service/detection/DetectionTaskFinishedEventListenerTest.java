package com.ruanzhu.doorhandle.module.detection.service.detection;

import com.ruanzhu.doorhandle.contracts.detection.DetectionTaskFinishedEvent;
import com.ruanzhu.doorhandle.module.detection.service.impl.DetectionTaskServiceImpl;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.mockito.Mockito.verify;

@ExtendWith(MockitoExtension.class)
class DetectionTaskFinishedEventListenerTest {

    @Mock
    private DetectionTaskServiceImpl detectionTaskService;

    @InjectMocks
    private DetectionTaskFinishedEventListener listener;

    @Test
    void appliesFinishedEventToTaskService() {
        DetectionTaskFinishedEvent event = DetectionTaskFinishedEvent.builder()
                .taskId("det_123")
                .status("COMPLETED")
                .resultJsonKey("detection/Result/detection_results.json")
                .build();

        listener.onFinished(event);

        verify(detectionTaskService).applyFinishedEvent(event);
    }
}
