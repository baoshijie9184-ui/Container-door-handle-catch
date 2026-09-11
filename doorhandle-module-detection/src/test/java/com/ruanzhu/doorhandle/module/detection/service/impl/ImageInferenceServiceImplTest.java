package com.ruanzhu.doorhandle.module.detection.service.impl;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.test.util.ReflectionTestUtils;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;

class ImageInferenceServiceImplTest {

    private final ImageInferenceServiceImpl imageInferenceService = new ImageInferenceServiceImpl();

    @TempDir
    Path tempDir;

    @Test
    void resolveModelPathFallsBackToConfiguredModelDirectoryForLegacyUrlPath() throws Exception {
        Path modelDir = tempDir.resolve("models");
        Files.createDirectories(modelDir);
        Path modelFile = modelDir.resolve("demo.onnx");
        Files.writeString(modelFile, "mock");

        ReflectionTestUtils.setField(imageInferenceService, "modelUploadDir", modelDir.toString());

        Path resolved = imageInferenceService.resolveModelPath("/uploads/models/demo.onnx");

        assertEquals(modelFile.toAbsolutePath().normalize(), resolved);
    }
}
