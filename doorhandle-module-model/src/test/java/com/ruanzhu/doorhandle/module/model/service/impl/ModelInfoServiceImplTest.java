package com.ruanzhu.doorhandle.module.model.service.impl;

import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.model.mapper.ModelInfoMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.LocalDateTime;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ModelInfoServiceImplTest {

    @Mock
    private ModelInfoMapper modelInfoMapper;

    @Mock
    private com.ruanzhu.doorhandle.module.model.service.ModelUploadFiles uploadFiles;

    private ModelInfoServiceImpl modelInfoService;

    @BeforeEach
    void setUp() {
        modelInfoService = new ModelInfoServiceImpl();
        ReflectionTestUtils.setField(modelInfoService, "uploadFiles", uploadFiles);
        ReflectionTestUtils.setField(modelInfoService, "baseMapper", modelInfoMapper);
    }

    @Test
    void updateModelInfoPreservesPersistedFieldsWhenRequestOmitsThem() {
        ModelInfo existing = new ModelInfo();
        existing.setModelId(8);
        existing.setModelName("door-handle");
        existing.setVersion("v1");
        existing.setModelPath("/uploads/models/demo.onnx");
        existing.setUploadTime(LocalDateTime.of(2026, 5, 1, 12, 0));
        existing.setUpdateDescription("old");

        ModelInfo patch = new ModelInfo();
        patch.setModelId(8);
        patch.setUpdateDescription("new");

        when(modelInfoMapper.selectOne(any(), anyBoolean())).thenReturn(existing);
        when(modelInfoMapper.updateById(any(ModelInfo.class))).thenReturn(1);

        boolean updated = modelInfoService.updateModelInfo(patch);

        ArgumentCaptor<ModelInfo> captor = ArgumentCaptor.forClass(ModelInfo.class);
        verify(modelInfoMapper).updateById(captor.capture());
        ModelInfo merged = captor.getValue();

        assertTrue(updated);
        assertEquals("door-handle", merged.getModelName());
        assertEquals("v1", merged.getVersion());
        assertEquals("/uploads/models/demo.onnx", merged.getModelPath());
        assertEquals(LocalDateTime.of(2026, 5, 1, 12, 0), merged.getUploadTime());
        assertEquals("new", merged.getUpdateDescription());
    }

    @Test
    void recordEvaluationStoresMetricsAndPerformanceForModel() {
        ModelInfo existing = new ModelInfo();
        existing.setModelId(8);
        existing.setStatus("READY");

        ModelInfo evaluation = new ModelInfo();
        evaluation.setModelId(8);
        evaluation.setEvaluationDataset("door-handle-val-2026Q2");
        evaluation.setPrecisionScore(new java.math.BigDecimal("0.9132"));
        evaluation.setRecallScore(new java.math.BigDecimal("0.8845"));
        evaluation.setMapScore(new java.math.BigDecimal("0.9021"));
        evaluation.setF1Score(new java.math.BigDecimal("0.8986"));
        evaluation.setAvgInferenceMs(42);
        evaluation.setCompatibilityNote("ONNX Runtime 1.17 / CPU");

        when(modelInfoMapper.selectOne(any(), anyBoolean())).thenReturn(existing);
        when(modelInfoMapper.updateById(any(ModelInfo.class))).thenReturn(1);

        boolean updated = modelInfoService.recordEvaluation(8, evaluation);

        ArgumentCaptor<ModelInfo> captor = ArgumentCaptor.forClass(ModelInfo.class);
        verify(modelInfoMapper).updateById(captor.capture());
        ModelInfo merged = captor.getValue();

        assertTrue(updated);
        assertEquals("door-handle-val-2026Q2", merged.getEvaluationDataset());
        assertEquals(new java.math.BigDecimal("0.9132"), merged.getPrecisionScore());
        assertEquals(new java.math.BigDecimal("0.8845"), merged.getRecallScore());
        assertEquals(new java.math.BigDecimal("0.9021"), merged.getMapScore());
        assertEquals(new java.math.BigDecimal("0.8986"), merged.getF1Score());
        assertEquals(42, merged.getAvgInferenceMs());
        assertEquals("ONNX Runtime 1.17 / CPU", merged.getCompatibilityNote());
        assertEquals("EVALUATED", merged.getMlopsStatus());
    }

    @Test
    void recordsMeasuredFactsAndDerivesRateUsingSuccessfulEvaluationImages() {
        ModelInfo existing = new ModelInfo();
        existing.setModelId(8);
        ModelInfo incoming = new ModelInfo();
        incoming.setTrainingImageCount(3200);
        incoming.setTrainingCompletedAt(LocalDateTime.of(2026, 10, 20, 18, 30));
        incoming.setEvaluationImageCount(98);
        incoming.setNoDetectionImageCount(3);
        incoming.setInferenceFps(new java.math.BigDecimal("12.3456"));
        incoming.setCompatibilityNote("CPU / 640x640 / batch=1 / 98 images / inference only");
        when(modelInfoMapper.selectOne(any(), anyBoolean())).thenReturn(existing);
        when(modelInfoMapper.updateById(any(ModelInfo.class))).thenReturn(1);
        assertTrue(modelInfoService.recordEvaluation(8, incoming));
        ArgumentCaptor<ModelInfo> saved = ArgumentCaptor.forClass(ModelInfo.class);
        verify(modelInfoMapper).updateById(saved.capture());
        assertEquals(3200, saved.getValue().getTrainingImageCount());
        assertEquals(incoming.getTrainingCompletedAt(), saved.getValue().getTrainingCompletedAt());
        assertEquals(new java.math.BigDecimal("0.03061224"), saved.getValue().getNoDetectionRate());
        assertEquals(incoming.getInferenceFps(), saved.getValue().getInferenceFps());
    }

    @Test
    void omittedNewFactsRemainAvailableForOlderClients() {
        ModelInfo existing = new ModelInfo();
        existing.setTrainingImageCount(3200);
        existing.setEvaluationImageCount(100);
        existing.setNoDetectionImageCount(0);
        when(modelInfoMapper.selectOne(any(), anyBoolean())).thenReturn(existing);
        when(modelInfoMapper.updateById(any(ModelInfo.class))).thenReturn(1);
        assertTrue(modelInfoService.recordEvaluation(8, new ModelInfo()));
        ArgumentCaptor<ModelInfo> saved = ArgumentCaptor.forClass(ModelInfo.class);
        verify(modelInfoMapper).updateById(saved.capture());
        assertEquals(3200, saved.getValue().getTrainingImageCount());
        assertEquals(new java.math.BigDecimal("0.00000000"), saved.getValue().getNoDetectionRate());
    }

    @Test
    void rejectsInventedRatesAndUnspecifiedFpsEnvironment() {
        ModelInfo existing = new ModelInfo();
        when(modelInfoMapper.selectOne(any(), anyBoolean())).thenReturn(existing);
        ModelInfo incoming = new ModelInfo();
        incoming.setEvaluationImageCount(10);
        incoming.setNoDetectionImageCount(11);
        assertThrows(BusinessException.class, () -> modelInfoService.recordEvaluation(8, incoming));
        incoming.setNoDetectionImageCount(0);
        incoming.setInferenceFps(new java.math.BigDecimal("25"));
        assertThrows(BusinessException.class, () -> modelInfoService.recordEvaluation(8, incoming));
        ModelInfo noSuccessfulImage = new ModelInfo();
        noSuccessfulImage.setEvaluationImageCount(0);
        noSuccessfulImage.setNoDetectionImageCount(0);
        org.junit.jupiter.api.Assertions.assertNull(noSuccessfulImage.getNoDetectionRate());
    }

    @Test
    void fractionalJsonImageCountsAreRejectedInsteadOfTruncated() {
        var json = new com.fasterxml.jackson.databind.ObjectMapper();
        assertThrows(com.fasterxml.jackson.databind.JsonMappingException.class,
                () -> json.readValue("{\"trainingImageCount\":1.5}", ModelInfo.class));
        assertThrows(com.fasterxml.jackson.databind.JsonMappingException.class,
                () -> json.readValue("{\"evaluationImageCount\":\"100\"}", ModelInfo.class));
    }

    @Test
    void configureRolloutStoresStrategyAndRollbackSource() {
        ModelInfo existing = new ModelInfo();
        existing.setModelId(9);
        existing.setStatus("PUBLISHED");

        when(modelInfoMapper.selectOne(any(), anyBoolean())).thenReturn(existing);
        when(modelInfoMapper.updateById(any(ModelInfo.class))).thenReturn(1);

        boolean updated = modelInfoService.configureRollout(9, "CANARY", 25, "B", 3);

        ArgumentCaptor<ModelInfo> captor = ArgumentCaptor.forClass(ModelInfo.class);
        verify(modelInfoMapper).updateById(captor.capture());
        ModelInfo merged = captor.getValue();

        assertTrue(updated);
        assertEquals("CANARY", merged.getDeploymentStrategy());
        assertEquals(25, merged.getCanaryPercent());
        assertEquals("B", merged.getAbGroup());
        assertEquals(3, merged.getRollbackFromModelId());
        assertEquals("ROLLOUT", merged.getMlopsStatus());
    }

    @Test
    void recordEvaluationRejectsMetricsOutsideZeroToOne() {
        ModelInfo existing = new ModelInfo();
        existing.setModelId(8);

        ModelInfo evaluation = new ModelInfo();
        evaluation.setPrecisionScore(new java.math.BigDecimal("1.2000"));
        evaluation.setRecallScore(new java.math.BigDecimal("0.8000"));
        evaluation.setMapScore(new java.math.BigDecimal("0.7000"));
        evaluation.setF1Score(new java.math.BigDecimal("0.7500"));
        evaluation.setAvgInferenceMs(30);

        when(modelInfoMapper.selectOne(any(), anyBoolean())).thenReturn(existing);

        BusinessException exception = assertThrows(
                BusinessException.class,
                () -> modelInfoService.recordEvaluation(8, evaluation)
        );

        assertEquals("模型评估指标必须在 0 到 1 之间", exception.getMessage());
    }

    @Test
    void configureRolloutRejectsUnknownStrategy() {
        ModelInfo existing = new ModelInfo();
        existing.setModelId(9);

        when(modelInfoMapper.selectOne(any(), anyBoolean())).thenReturn(existing);

        BusinessException exception = assertThrows(
                BusinessException.class,
                () -> modelInfoService.configureRollout(9, "EXPERIMENTAL", 10, "A", null)
        );

        assertEquals("不支持的部署策略: EXPERIMENTAL", exception.getMessage());
    }

    @Test
    void configureRollbackRejectsMissingSourceModel() {
        ModelInfo existing = new ModelInfo();
        existing.setModelId(9);

        when(modelInfoMapper.selectOne(any(), anyBoolean())).thenReturn(existing, null);

        BusinessException exception = assertThrows(
                BusinessException.class,
                () -> modelInfoService.configureRollout(9, "ROLLBACK", 0, null, 3)
        );

        assertEquals("回滚来源模型不存在", exception.getMessage());
    }

    @Test
    void configureRollbackRejectsUnpublishedSourceModel() {
        ModelInfo existing = new ModelInfo();
        existing.setModelId(9);

        ModelInfo source = new ModelInfo();
        source.setModelId(3);
        source.setStatus("READY");

        when(modelInfoMapper.selectOne(any(), anyBoolean())).thenReturn(existing, source);

        BusinessException exception = assertThrows(
                BusinessException.class,
                () -> modelInfoService.configureRollout(9, "ROLLBACK", 0, null, 3)
        );

        assertEquals("只能回滚到已发布模型", exception.getMessage());
    }
}
