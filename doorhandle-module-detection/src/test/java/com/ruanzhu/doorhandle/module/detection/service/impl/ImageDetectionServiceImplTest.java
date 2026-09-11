package com.ruanzhu.doorhandle.module.detection.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.dto.ImageDetectionResponse;
import com.ruanzhu.doorhandle.module.detection.dto.SingleImageDetectionResponse;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.model.mapper.ModelInfoMapper;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.detection.service.ImageInferenceService;
import com.ruanzhu.doorhandle.module.model.service.ModelService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;

import java.math.BigDecimal;
import java.io.File;
import java.io.IOException;
import java.nio.file.NoSuchFileException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.never;

@ExtendWith(MockitoExtension.class)
class ImageDetectionServiceImplTest {

    @Mock
    private ModelInfoMapper modelInfoMapper;

    @Mock
    private DetectionTaskMapper detectionTaskMapper;

    @Mock
    private ModelService modelService;

    @Mock
    private ImageInferenceService imageInferenceService;

    @Mock
    private ImageDetectionAsyncService imageDetectionAsyncService;

    @Spy
    private DetectionTaskAccessPolicy detectionTaskAccessPolicy = new DetectionTaskAccessPolicy();

    @InjectMocks
    private ImageDetectionServiceImpl imageDetectionService;

    @TempDir
    Path tempDir;

    @BeforeEach
    void setUp() {
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(
                        "admin",
                        "N/A",
                        List.of(new SimpleGrantedAuthority("ROLE_ADMIN"))));
        ReflectionTestUtils.setField(imageDetectionService, "objectMapper", new ObjectMapper());
        ReflectionTestUtils.setField(imageDetectionService, "maxImagesPerBatch", 200);
        ReflectionTestUtils.setField(imageDetectionService, "maxImageBytes", 10L * 1024L * 1024L);
    }

    @AfterEach
    void clearAuthentication() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void processImageDetectionSchedulesAsyncExecutionInsteadOfRunningInline() {
        ModelInfo modelInfo = new ModelInfo();
        modelInfo.setModelId(7);
        modelInfo.setModelName("demo");
        modelInfo.setModelPath(tempDir.resolve("model.onnx").toString());
        when(modelInfoMapper.selectByModelId(7)).thenReturn(modelInfo);

        ArgumentCaptor<DetectionTask> taskCaptor = ArgumentCaptor.forClass(DetectionTask.class);
        when(detectionTaskMapper.insert(taskCaptor.capture())).thenAnswer(invocation -> {
            DetectionTask task = taskCaptor.getValue();
            ReflectionTestUtils.setField(task, "id", 99L);
            return 1;
        });

        ReflectionTestUtils.setField(imageDetectionService, "imageUploadDir", tempDir.resolve("images").toString());
        ReflectionTestUtils.setField(imageDetectionService, "resultDir", tempDir.resolve("results").toString());
        ReflectionTestUtils.setField(imageDetectionService, "annotatedDir", tempDir.resolve("annotated").toString());
        ReflectionTestUtils.setField(imageDetectionService, "uploadDir", tempDir.resolve("images").toString());
        ReflectionTestUtils.setField(imageDetectionService, "modelsDir", tempDir.resolve("models").toString());
        ReflectionTestUtils.setField(imageDetectionService, "defaultModelFile", "default.onnx");

        MockMultipartFile file = new MockMultipartFile(
                "files",
                "sample.jpg",
                "image/jpeg",
                "demo-image".getBytes()
        );

        ImageDetectionResponse response = imageDetectionService.processImageDetection(
                List.of(file),
                7,
                "COCO",
                0.5f
        );

        assertEquals("PROCESSING", response.getStatus());
        assertEquals(99L, response.getId());
        verify(imageDetectionAsyncService, times(1))
                .performDetectionAsync(any(DetectionTask.class), any(List.class), any(ModelInfo.class), any(String.class), any(Float.class));
        assertNotNull(taskCaptor.getValue().getSourceOssPrefix());
    }

    @Test
    void deleteDetectionDataRemovesAnnotatedDirectoryAlongsideSourceAndResult() throws Exception {
        Path imageDir = tempDir.resolve("images").resolve("detect_001");
        Path resultDir = tempDir.resolve("results").resolve("detect_001");
        Path annotatedDir = tempDir.resolve("annotated").resolve("detect_001");
        Files.createDirectories(imageDir);
        Files.createDirectories(resultDir);
        Files.createDirectories(annotatedDir);
        Files.writeString(imageDir.resolve("source.jpg"), "src");
        Files.writeString(resultDir.resolve("result.txt"), "result");
        Files.writeString(annotatedDir.resolve("annotated.jpg"), "annotated");

        DetectionTask task = new DetectionTask();
        task.setId(10L);
        task.setSourceOssPrefix(imageDir.toString());
        task.setResultOssPrefix(resultDir.toString());
        when(detectionTaskMapper.selectById(10L)).thenReturn(task);

        imageDetectionService.deleteDetectionData(10L);

        assertFalse(Files.exists(imageDir));
        assertFalse(Files.exists(resultDir));
        assertFalse(Files.exists(annotatedDir));
        verify(detectionTaskMapper).deleteById(10L);
    }

    @Test
    void deleteDetectionDataAllowsForeignTaskForOperator() {
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(
                        "alice",
                        "N/A",
                        List.of(new SimpleGrantedAuthority("ROLE_OPERATOR"))));
        DetectionTask task = new DetectionTask();
        task.setId(10L);
        task.setCreatedBy("bob");
        when(detectionTaskMapper.selectById(10L)).thenReturn(task);

        imageDetectionService.deleteDetectionData(10L);

        verify(detectionTaskMapper).deleteById(10L);
    }

    @Test
    void processImageDetectionRejectsTooManyImagesBeforeCreatingTask() {
        ReflectionTestUtils.setField(imageDetectionService, "maxImagesPerBatch", 1);

        MockMultipartFile first = new MockMultipartFile("files", "a.jpg", "image/jpeg", "a".getBytes());
        MockMultipartFile second = new MockMultipartFile("files", "b.jpg", "image/jpeg", "b".getBytes());

        BusinessException exception = assertThrows(
                BusinessException.class,
                () -> imageDetectionService.processImageDetection(List.of(first, second), 7, "COCO", 0.5f)
        );

        assertEquals("单次最多上传 1 张图片", exception.getMessage());
    }

    @Test
    void processImageDetectionRejectsUnsupportedImageContentType() {
        MockMultipartFile file = new MockMultipartFile(
                "files",
                "sample.jpg",
                "text/plain",
                "not-image".getBytes()
        );

        BusinessException exception = assertThrows(
                BusinessException.class,
                () -> imageDetectionService.processImageDetection(List.of(file), 7, "COCO", 0.5f)
        );

        assertEquals("图片 Content-Type 不受支持: text/plain", exception.getMessage());
    }

    @Test
    void detectImageRejectsOversizedImageWithUserFacingError() {
        ReflectionTestUtils.setField(imageDetectionService, "maxImageBytes", 4L);

        MockMultipartFile file = new MockMultipartFile(
                "file",
                "sample.jpg",
                "image/jpeg",
                "too-large".getBytes()
        );

        SingleImageDetectionResponse response = imageDetectionService.detectImage(file, 7);

        assertEquals("图片文件不能超过 4B", response.getErrorMessage());
    }

    @Test
    void detectImagePersistsTaskStatisticsConsistentWithConfidenceThreshold() throws Exception {
        ModelInfo modelInfo = new ModelInfo();
        modelInfo.setModelId(7);
        modelInfo.setModelName("demo");
        modelInfo.setVersion("v1");
        modelInfo.setModelPath(tempDir.resolve("model.onnx").toString());
        when(modelInfoMapper.selectByModelId(7)).thenReturn(modelInfo);
        when(imageInferenceService.classify(any(Path.class), eq(modelInfo.getModelPath())))
                .thenReturn(new ImageInferenceService.ClassificationResult("Bent", 0.2f, Map.of("Bent", 0.2f)));

        ArgumentCaptor<DetectionTask> taskCaptor = ArgumentCaptor.forClass(DetectionTask.class);
        when(detectionTaskMapper.insert(taskCaptor.capture())).thenReturn(1);

        ReflectionTestUtils.setField(imageDetectionService, "annotatedDir", tempDir.resolve("annotated").toString());
        ReflectionTestUtils.setField(imageDetectionService, "uploadDir", tempDir.resolve("images").toString());

        MockMultipartFile file = new MockMultipartFile(
                "file",
                "sample.jpg",
                "image/jpeg",
                "demo-image".getBytes()
        );

        SingleImageDetectionResponse response = imageDetectionService.detectImage(file, 7);

        assertEquals("Bent", response.getCategory());
        DetectionTask persistedTask = taskCaptor.getValue();
        assertEquals(0, persistedTask.getSuccessfulImages());
        assertEquals(1, persistedTask.getFailedImages());
        assertEquals(BigDecimal.valueOf(0.5), persistedTask.getThreshold());

        @SuppressWarnings("unchecked")
        Map<String, Object> statistics = new ObjectMapper().readValue(persistedTask.getStatisticsJson(), Map.class);
        assertEquals(100.0, ((Number) statistics.get("missDetectionRate")).doubleValue());
        assertTrue(persistedTask.getResultOssPrefix().contains("annotated"));
    }

    @Test
    void detectImageSupportsRelativeUploadDirectoryWithServletMultipartFile() {
        ModelInfo modelInfo = new ModelInfo();
        modelInfo.setModelId(7);
        modelInfo.setVersion("v1");
        modelInfo.setModelPath(tempDir.resolve("model.onnx").toString());
        when(modelInfoMapper.selectByModelId(7)).thenReturn(modelInfo);
        when(imageInferenceService.classify(any(Path.class), eq(modelInfo.getModelPath())))
                .thenReturn(new ImageInferenceService.ClassificationResult("Normal", 0.9f, Map.of("Normal", 0.9f)));

        Path workingDirectory = Path.of("").toAbsolutePath().normalize();
        String relativeUploadDir = workingDirectory.relativize(tempDir.resolve("images").toAbsolutePath()).toString();
        String relativeAnnotatedDir = workingDirectory.relativize(tempDir.resolve("annotated").toAbsolutePath()).toString();
        ReflectionTestUtils.setField(imageDetectionService, "uploadDir", relativeUploadDir);
        ReflectionTestUtils.setField(imageDetectionService, "annotatedDir", relativeAnnotatedDir);

        MockMultipartFile file = servletStyleMultipartFile("file", "sample.jpg", "demo-image".getBytes());

        SingleImageDetectionResponse response = imageDetectionService.detectImage(file, 7);

        assertEquals("Normal", response.getCategory());
        assertEquals(null, response.getErrorMessage());
        verify(imageInferenceService).classify(any(Path.class), eq(modelInfo.getModelPath()));
    }

    @Test
    void processImageDetectionSupportsRelativeUploadDirectoryWithServletMultipartFile() {
        ModelInfo modelInfo = new ModelInfo();
        modelInfo.setModelId(7);
        modelInfo.setModelPath(tempDir.resolve("model.onnx").toString());
        when(modelInfoMapper.selectByModelId(7)).thenReturn(modelInfo);
        when(detectionTaskMapper.insert(any(DetectionTask.class))).thenAnswer(invocation -> {
            DetectionTask task = invocation.getArgument(0);
            ReflectionTestUtils.setField(task, "id", 101L);
            return 1;
        });

        Path workingDirectory = Path.of("").toAbsolutePath().normalize();
        ReflectionTestUtils.setField(imageDetectionService, "imageUploadDir",
                workingDirectory.relativize(tempDir.resolve("images").toAbsolutePath()).toString());
        ReflectionTestUtils.setField(imageDetectionService, "resultDir",
                workingDirectory.relativize(tempDir.resolve("results").toAbsolutePath()).toString());
        ReflectionTestUtils.setField(imageDetectionService, "annotatedDir",
                workingDirectory.relativize(tempDir.resolve("annotated").toAbsolutePath()).toString());

        MockMultipartFile file = servletStyleMultipartFile("files", "sample.jpg", "demo-image".getBytes());

        ImageDetectionResponse response = imageDetectionService.processImageDetection(
                List.of(file), 7, "COCO", 0.5f);

        assertEquals("PROCESSING", response.getStatus());
        assertEquals(101L, response.getId());
    }

    private MockMultipartFile servletStyleMultipartFile(String name, String filename, byte[] content) {
        return new MockMultipartFile(name, filename, "image/jpeg", content) {
            @Override
            public void transferTo(File destination) throws IOException {
                if (!destination.isAbsolute()) {
                    throw new IOException(new NoSuchFileException(
                            tempDir.resolve(destination.getPath()).toString()));
                }
                super.transferTo(destination);
            }
        };
    }
}
