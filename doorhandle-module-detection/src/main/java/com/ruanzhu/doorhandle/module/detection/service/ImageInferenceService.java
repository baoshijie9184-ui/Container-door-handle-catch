package com.ruanzhu.doorhandle.module.detection.service;

import java.nio.file.Path;
import java.util.Map;

public interface ImageInferenceService {

    ClassificationResult classify(Path imagePath, String modelPath);

    void renderAnnotatedImage(Path imagePath, String category, float confidence, Path outputPath);

    record ClassificationResult(String category, float confidence, Map<String, Float> confidences) {
    }
}
