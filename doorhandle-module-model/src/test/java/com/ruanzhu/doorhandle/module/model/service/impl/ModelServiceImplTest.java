package com.ruanzhu.doorhandle.module.model.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.module.model.entity.ModelOperationLog;
import com.ruanzhu.doorhandle.module.model.mapper.ModelInfoMapper;
import com.ruanzhu.doorhandle.module.model.mapper.ModelOperationLogMapper;
import com.ruanzhu.doorhandle.module.model.service.ModelValidationService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.util.ReflectionTestUtils;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.stream.Stream;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.ruanzhu.doorhandle.common.BusinessException;

@ExtendWith(MockitoExtension.class)
class ModelServiceImplTest {

    @Mock
    private ModelInfoMapper modelInfoMapper;

    @Mock
    private ModelOperationLogMapper modelOperationLogMapper;

    @Mock
    private ModelValidationService modelValidationService;

    @InjectMocks
    private ModelServiceImpl modelService;

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(modelService, "maxUploadBytes", 209715200L);
    }

    @Test
    void uploadModelRetriesWithFreshModelIdWhenDuplicateKeyOccurs() throws Exception {
        Path uploadDir = Files.createTempDirectory("model-upload-test");
        ReflectionTestUtils.setField(modelService, "modelUploadDir", uploadDir.toString());

        when(modelInfoMapper.selectByModelNameAndVersion("door-handle", "v1")).thenReturn(null);
        when(modelInfoMapper.selectNextModelId()).thenReturn(10, 11);
        when(modelValidationService.validate(any(Path.class)))
                .thenReturn(new ModelValidationService.ValidationResult("PASSED", "ONNX 加载成功"));

        ArgumentCaptor<ModelInfo> insertCaptor = ArgumentCaptor.forClass(ModelInfo.class);
        when(modelInfoMapper.insert(insertCaptor.capture()))
                .thenThrow(new DuplicateKeyException("duplicate model_id"))
                .thenReturn(1);

        ModelInfo persisted = new ModelInfo();
        persisted.setModelId(11);
        persisted.setModelName("door-handle");
        persisted.setVersion("v1");
        when(modelInfoMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(persisted);

        MockMultipartFile file = new MockMultipartFile(
                "file",
                "model.onnx",
                "application/octet-stream",
                "fake-onnx".getBytes()
        );

        ModelInfo result = modelService.uploadModel(file, "door-handle", "v1", "desc");

        assertEquals(11, result.getModelId());
        assertTrue(Files.exists(uploadDir));
        verify(modelInfoMapper, times(2)).selectNextModelId();
        verify(modelInfoMapper, never()).selectAll();
        assertEquals(11, insertCaptor.getAllValues().get(1).getModelId());
        assertEquals("READY", insertCaptor.getAllValues().get(1).getStatus());
        assertEquals("PASSED", insertCaptor.getAllValues().get(1).getValidationStatus());
        assertEquals("ONNX 加载成功", insertCaptor.getAllValues().get(1).getValidationMessage());
        assertEquals("UNASSESSED", insertCaptor.getAllValues().get(1).getMlopsStatus());
        assertEquals("FULL", insertCaptor.getAllValues().get(1).getDeploymentStrategy());
        assertEquals(100, insertCaptor.getAllValues().get(1).getCanaryPercent());
        verify(modelOperationLogMapper).insert(any(ModelOperationLog.class));
    }

    @Test
    void uploadModelRejectsNonOnnxFiles() throws Exception {
        Path uploadDir = Files.createTempDirectory("model-upload-test");
        ReflectionTestUtils.setField(modelService, "modelUploadDir", uploadDir.toString());

        MockMultipartFile file = new MockMultipartFile(
                "file",
                "model.txt",
                "text/plain",
                "not-an-onnx".getBytes()
        );

        BusinessException exception = assertThrows(
                BusinessException.class,
                () -> modelService.uploadModel(file, "door-handle", "v1", "desc")
        );

        assertEquals("仅支持上传 ONNX 格式文件", exception.getMessage());
        try (Stream<Path> files = Files.list(uploadDir)) {
            assertEquals(0L, files.count());
        }
        verify(modelInfoMapper, never()).insert(any(ModelInfo.class));
    }

    @Test
    void uploadModelRejectsOversizedFilesBeforePersistence() throws Exception {
        Path uploadDir = Files.createTempDirectory("model-upload-test");
        ReflectionTestUtils.setField(modelService, "modelUploadDir", uploadDir.toString());
        ReflectionTestUtils.setField(modelService, "maxUploadBytes", 4L);

        MockMultipartFile file = new MockMultipartFile(
                "file",
                "model.onnx",
                "application/octet-stream",
                "too-large".getBytes()
        );

        BusinessException exception = assertThrows(
                BusinessException.class,
                () -> modelService.uploadModel(file, "door-handle", "v1", "desc")
        );

        assertEquals("模型文件不能超过 4B", exception.getMessage());
        try (Stream<Path> files = Files.list(uploadDir)) {
            assertEquals(0L, files.count());
        }
        verify(modelInfoMapper, never()).selectByModelNameAndVersion(any(), any());
        verify(modelInfoMapper, never()).insert(any(ModelInfo.class));
    }

    @Test
    void uploadModelDeletesSavedFileWhenPersistenceFails() throws Exception {
        Path uploadDir = Files.createTempDirectory("model-upload-test");
        ReflectionTestUtils.setField(modelService, "modelUploadDir", uploadDir.toString());

        when(modelInfoMapper.selectByModelNameAndVersion("door-handle", "v1")).thenReturn(null);
        when(modelInfoMapper.selectNextModelId()).thenReturn(10);
        when(modelValidationService.validate(any(Path.class)))
                .thenReturn(new ModelValidationService.ValidationResult("PASSED", "ONNX 加载成功"));
        when(modelInfoMapper.insert(any(ModelInfo.class))).thenReturn(1);
        when(modelInfoMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);

        MockMultipartFile file = new MockMultipartFile(
                "file",
                "model.onnx",
                "application/octet-stream",
                "fake-onnx".getBytes()
        );

        BusinessException exception = assertThrows(
                BusinessException.class,
                () -> modelService.uploadModel(file, "door-handle", "v1", "desc")
        );

        assertEquals("模型信息保存失败", exception.getMessage());
        try (Stream<Path> files = Files.list(uploadDir)) {
            assertEquals(0L, files.count());
        }
        assertFalse(Files.notExists(uploadDir));
    }

    @Test
    void uploadModelPersistsFailedValidationAsDraft() throws Exception {
        Path uploadDir = Files.createTempDirectory("model-upload-test");
        ReflectionTestUtils.setField(modelService, "modelUploadDir", uploadDir.toString());

        when(modelInfoMapper.selectByModelNameAndVersion("door-handle", "v1")).thenReturn(null);
        when(modelInfoMapper.selectNextModelId()).thenReturn(12);
        when(modelValidationService.validate(any(Path.class)))
                .thenReturn(new ModelValidationService.ValidationResult("FAILED", "ONNX 加载失败: invalid protobuf"));

        ArgumentCaptor<ModelInfo> insertCaptor = ArgumentCaptor.forClass(ModelInfo.class);
        when(modelInfoMapper.insert(insertCaptor.capture())).thenReturn(1);

        ModelInfo persisted = new ModelInfo();
        persisted.setModelId(12);
        persisted.setModelName("door-handle");
        persisted.setVersion("v1");
        persisted.setStatus("DRAFT");
        persisted.setValidationStatus("FAILED");
        persisted.setValidationMessage("ONNX 加载失败: invalid protobuf");
        when(modelInfoMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(persisted);

        MockMultipartFile file = new MockMultipartFile(
                "file",
                "model.onnx",
                "application/octet-stream",
                "fake-onnx".getBytes()
        );

        ModelInfo result = modelService.uploadModel(file, "door-handle", "v1", "desc");

        assertEquals("DRAFT", result.getStatus());
        assertEquals("FAILED", result.getValidationStatus());
        assertEquals("DRAFT", insertCaptor.getValue().getStatus());
        assertEquals("FAILED", insertCaptor.getValue().getValidationStatus());
        assertEquals("ONNX 加载失败: invalid protobuf", insertCaptor.getValue().getValidationMessage());
    }

    @Test
    void publishAndSetDefaultModelUpdatesLifecycleFlags() {
        ModelInfo readyModel = new ModelInfo();
        readyModel.setModelId(8);
        readyModel.setModelName("door-handle");
        readyModel.setVersion("v2");
        readyModel.setStatus("READY");
        readyModel.setValidationStatus("PASSED");

        ModelInfo previousDefault = new ModelInfo();
        previousDefault.setModelId(3);
        previousDefault.setModelName("door-handle");
        previousDefault.setVersion("v1");
        previousDefault.setStatus("PUBLISHED");
        previousDefault.setIsDefault(true);

        when(modelInfoMapper.selectOne(any(LambdaQueryWrapper.class)))
                .thenReturn(readyModel)
                .thenReturn(readyModel)
                .thenReturn(previousDefault)
                .thenReturn(readyModel);
        when(modelInfoMapper.updateModelRecord(any(ModelInfo.class))).thenReturn(1);

        ModelInfo published = modelService.publishModel(8);
        ModelInfo defaultModel = modelService.setDefaultModel(8);

        assertEquals("PUBLISHED", published.getStatus());
        assertEquals("PUBLISHED", defaultModel.getStatus());
        assertEquals(Boolean.TRUE, defaultModel.getIsDefault());
        assertTrue(defaultModel.getPublishedAt() != null);
        verify(modelInfoMapper, times(2)).updateModelRecord(any(ModelInfo.class));
        verify(modelOperationLogMapper, times(2)).insert(any(ModelOperationLog.class));
    }

    @Test
    void publishModelRejectsFailedValidation() {
        ModelInfo readyModel = new ModelInfo();
        readyModel.setModelId(8);
        readyModel.setStatus("READY");
        readyModel.setValidationStatus("FAILED");
        readyModel.setValidationMessage("ONNX 加载失败");

        when(modelInfoMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(readyModel);

        BusinessException exception = assertThrows(BusinessException.class, () -> modelService.publishModel(8));

        assertEquals("模型校验未通过，不能发布", exception.getMessage());
        verify(modelInfoMapper, never()).updateModelRecord(any(ModelInfo.class));
        verify(modelOperationLogMapper, never()).insert(any(ModelOperationLog.class));
    }

    @Test
    void validateModelMarksDraftModelReadyWhenOnnxValidationPasses() {
        ModelInfo draftModel = new ModelInfo();
        draftModel.setModelId(13);
        draftModel.setModelPath("C:/models/door.onnx");
        draftModel.setStatus("DRAFT");
        draftModel.setValidationStatus("FAILED");

        when(modelInfoMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(draftModel);
        when(modelValidationService.validate(Path.of("C:/models/door.onnx")))
                .thenReturn(new ModelValidationService.ValidationResult("PASSED", "ONNX 加载成功"));

        ModelInfo result = modelService.validateModel(13);

        assertEquals("READY", result.getStatus());
        assertEquals("PASSED", result.getValidationStatus());
        assertEquals("ONNX 加载成功", result.getValidationMessage());
        verify(modelInfoMapper).updateModelRecord(any(ModelInfo.class));
        verify(modelOperationLogMapper).insert(any(ModelOperationLog.class));
    }

    @Test
    void validateModelKeepsModelDraftWhenOnnxValidationFails() {
        ModelInfo model = new ModelInfo();
        model.setModelId(14);
        model.setModelPath("C:/models/broken.onnx");
        model.setStatus("READY");
        model.setValidationStatus("PASSED");

        when(modelInfoMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(model);
        when(modelValidationService.validate(Path.of("C:/models/broken.onnx")))
                .thenReturn(new ModelValidationService.ValidationResult("FAILED", "ONNX 加载失败: invalid graph"));

        ModelInfo result = modelService.validateModel(14);

        assertEquals("DRAFT", result.getStatus());
        assertEquals(Boolean.FALSE, result.getIsDefault());
        assertEquals("FAILED", result.getValidationStatus());
        assertEquals("ONNX 加载失败: invalid graph", result.getValidationMessage());
        verify(modelInfoMapper).updateModelRecord(any(ModelInfo.class));
        verify(modelOperationLogMapper).insert(any(ModelOperationLog.class));
    }

    @Test
    void disableArchiveAndUsageUpdateAdjustOperationalFields() {
        ModelInfo model = new ModelInfo();
        model.setModelId(9);
        model.setStatus("PUBLISHED");
        model.setIsDefault(true);
        model.setUsageCount(2);

        when(modelInfoMapper.selectOne(any(LambdaQueryWrapper.class)))
                .thenReturn(model)
                .thenReturn(model)
                .thenReturn(model);
        when(modelInfoMapper.updateModelRecord(any(ModelInfo.class))).thenReturn(1);

        ModelInfo disabled = modelService.disableModel(9);
        assertEquals("DISABLED", disabled.getStatus());
        assertEquals(Boolean.FALSE, disabled.getIsDefault());

        ModelInfo archived = modelService.archiveModel(9);
        modelService.incrementUsageStats(9, LocalDateTime.of(2026, 6, 1, 10, 0));

        assertEquals("ARCHIVED", archived.getStatus());
        assertEquals(3, model.getUsageCount());
        assertEquals(LocalDateTime.of(2026, 6, 1, 10, 0), model.getLastUsedAt());
        verify(modelOperationLogMapper, times(2)).insert(any(ModelOperationLog.class));
    }
}
