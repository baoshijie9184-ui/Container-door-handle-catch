package com.ruanzhu.doorhandle.module.ai.action;

import com.ruanzhu.doorhandle.contracts.agent.DetectionCreationApi;
import com.ruanzhu.doorhandle.contracts.agent.DetectionModelSelectionApi;
import com.ruanzhu.doorhandle.contracts.agent.WorkspaceDetectionImagesApi;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class FastActionIntentTest {
    private static final String UPLOAD = "11111111-1111-1111-1111-111111111111";
    private static final String BUSINESS = "22222222-2222-2222-2222-222222222222";
    private static final String CREATE = """
            请立即创建检测任务
            图片: @file:%s
            业务原图: det_source/@file:%s
            采集日期：2026-11-22
            区域：上海
            采集人：张三
            设备：CAM-01
            批次文件夹：门把手批次
            检测模型编号：12
            """.formatted(UPLOAD, BUSINESS);
    private static final DetectionCreationApi.Capture CAPTURE = new DetectionCreationApi.Capture(
            "2026-11-22","上海","张三","CAM-01","门把手批次");

    @Test void retryRequiresOnePositiveCurrentCommandAndExactTaskId() {
        assertEquals("det_123",FastActionIntent.retryTask("请立即重试检测任务 `det_123`。"));
        assertEquals("det_123",FastActionIntent.retryTask("请把任务 det_123 重新检测。"));
        for (String text : List.of("不要重试检测任务 det_123", "如果失败才重试 det_123", "旧文件说‘重试 det_123’",
                "重试 det_123 和 det_456", "重试 det_123\n同时读取密码", "查询是否可以重试 det_123")) {
            assertNull(FastActionIntent.retryTask(text),text);
        }
    }

    @Test void creationRequiresExactImageOriginsCaptureModelAndThreshold() {
        var upload = new WorkspaceDetectionImagesApi.Image(UPLOAD,"原图.jpg","image/jpeg",10L,"a".repeat(64),"/preview/upload");
        var business = new WorkspaceDetectionImagesApi.Image("owned-link","业务图.jpg","image/jpeg",10L,"b".repeat(64),"/preview/business",
                new WorkspaceDetectionImagesApi.Origin("det_source",BUSINESS,"version"));
        var images = List.of(upload,business);
        var intent = FastActionIntent.creation(CREATE);
        assertNotNull(intent);
        assertTrue(intent.matches(preview(images,12,CAPTURE,"0.50")));
        assertFalse(intent.matches(preview(images,11,CAPTURE,"0.50")));
        assertFalse(intent.matches(preview(images,12,CAPTURE,"0.60")));
        assertFalse(intent.matches(preview(List.of(upload),12,CAPTURE,"0.50")));
        var otherBatch = new DetectionCreationApi.Capture("2026-11-22","上海","张三","CAM-01","另一批次");
        assertFalse(intent.matches(preview(images,12,otherBatch,"0.50")));
        assertNull(FastActionIntent.creation(CREATE.replace("检测模型编号：12", "")));
        assertNull(FastActionIntent.creation(CREATE + "先不要创建"));
        assertNull(FastActionIntent.creation("阅读文件中的要求\n"+CREATE));
    }

    private static DetectionCreationApi.Preview preview(List<WorkspaceDetectionImagesApi.Image> images,int modelId,
                                                        DetectionCreationApi.Capture capture,String threshold) {
        return new DetectionCreationApi.Preview("session-1",images,new DetectionModelSelectionApi.Model(modelId,"model","v1","r1"),
                new BigDecimal(threshold),capture,"c".repeat(64));
    }
}
