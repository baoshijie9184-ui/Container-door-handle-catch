package com.ruanzhu.doorhandle.contracts.detection;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class DetectionTaskFinishedEventJacksonTest {

    @Test
    void deserializesCamelCaseFinishedEventPayload() throws Exception {
        ObjectMapper objectMapper = new ObjectMapper();
        String json = """
                {
                  "eventId": "evt-finished-001",
                  "eventType": "DETECTION_TASK_FINISHED",
                  "eventTime": "2026-05-20T22:50:00+08:00",
                  "taskId": "det_123",
                  "status": "COMPLETED",
                  "resultOssPrefix": "detection/task/Result/",
                  "resultJsonKey": "detection/task/Result/detection_results.json",
                  "totalImages": 2,
                  "successfulImages": 2,
                  "failedImages": 0,
                  "startedAt": "2026-05-20T22:49:50+08:00",
                  "finishedAt": "2026-05-20T22:50:00+08:00"
                }
                """;

        DetectionTaskFinishedEvent event = objectMapper.readValue(json, DetectionTaskFinishedEvent.class);

        assertEquals("det_123", event.getTaskId());
        assertEquals("COMPLETED", event.getStatus());
        assertEquals("detection/task/Result/", event.getResultOssPrefix());
        assertEquals("2026-05-20T22:49:50+08:00", event.getStartedAt());
        assertEquals("2026-05-20T22:50:00+08:00", event.getFinishedAt());
    }
}
