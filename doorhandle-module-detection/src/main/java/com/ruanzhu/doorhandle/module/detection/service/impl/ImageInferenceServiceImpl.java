package com.ruanzhu.doorhandle.module.detection.service.impl;

import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtException;
import ai.onnxruntime.OrtSession;
import com.ruanzhu.doorhandle.module.detection.service.ImageInferenceService;
import com.ruanzhu.doorhandle.module.model.util.OnnxImageDetectionUtil;
import lombok.extern.slf4j.Slf4j;
import org.opencv.core.Mat;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Map;

@Service
@Slf4j
public class ImageInferenceServiceImpl implements ImageInferenceService {

    @Value("${model.upload-dir:${user.dir}/uploads/models}")
    private String modelUploadDir;

    @Override
    public ClassificationResult classify(Path imagePath, String modelPath) {
        Mat processedImage = null;
        try {
            processedImage = OnnxImageDetectionUtil.preProcessImage(imagePath.toString());
            try (OrtSession session = OnnxImageDetectionUtil.loadModel(resolveModelPath(modelPath).toString());
                 OnnxTensor inputTensor = OnnxImageDetectionUtil.imageToTensor(OrtEnvironment.getEnvironment(), processedImage)) {
                Map<String, Float> confidences = OnnxImageDetectionUtil.runInference(session, inputTensor);
                Map.Entry<String, Float> topCategory = OnnxImageDetectionUtil.getTopCategory(confidences);
                float confidence = normalizeConfidence(topCategory.getValue());
                return new ClassificationResult(topCategory.getKey(), confidence, confidences);
            }
        } catch (OrtException e) {
            throw new IllegalStateException("模型推理失败: " + e.getMessage(), e);
        } finally {
            if (processedImage != null) {
                processedImage.release();
            }
        }
    }

    @Override
    public void renderAnnotatedImage(Path imagePath, String category, float confidence, Path outputPath) {
        OnnxImageDetectionUtil.drawDetectionResult(
                imagePath.toString(),
                category,
                normalizeConfidence(confidence),
                outputPath.toString()
        );
    }

    Path resolveModelPath(String modelPath) {
        Path candidate = Paths.get(modelPath).toAbsolutePath().normalize();
        if (Files.exists(candidate)) {
            return candidate;
        }

        String normalized = modelPath.replace('\\', '/');
        String fileName = normalized.substring(normalized.lastIndexOf('/') + 1);
        Path fallback = Paths.get(modelUploadDir).resolve(fileName).toAbsolutePath().normalize();
        if (Files.exists(fallback)) {
            log.info("Resolved legacy model path {} to {}", modelPath, fallback);
            return fallback;
        }

        throw new IllegalStateException("模型文件不存在: " + modelPath);
    }

    private float normalizeConfidence(Float confidence) {
        if (confidence == null || Float.isNaN(confidence) || Float.isInfinite(confidence)) {
            log.warn("Detected invalid confidence: {}", confidence);
            return 0.0f;
        }
        return Math.max(0.0f, Math.min(1.0f, confidence));
    }
}
