package com.ruanzhu.doorhandle.module.detection.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.service.ImageInferenceService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

@Service
@RequiredArgsConstructor
@Slf4j
public class ImageDetectionAsyncService {

    private final DetectionTaskMapper detectionTaskMapper;
    private final ImageInferenceService imageInferenceService;
    private final ObjectMapper objectMapper;

    @Async
    public CompletableFuture<Void> performDetectionAsync(
            DetectionTask task,
            List<Path> savedImagePaths,
            ModelInfo modelInfo,
            String outputFormat,
            Float confidenceThreshold
    ) {
        try {
            processDetection(task, savedImagePaths, modelInfo, outputFormat, confidenceThreshold);
        } catch (Exception e) {
            log.error("批量检测任务失败, taskId={}", task.getTaskId(), e);
            task.setStatus("FAILED");
            task.setStage("FAILED");
            task.setErrorMessage("检测异常: " + e.getMessage());
            task.setFinishedAt(LocalDateTime.now());
            task.setUpdatedAt(LocalDateTime.now());
            detectionTaskMapper.updateById(task);
        }
        return CompletableFuture.completedFuture(null);
    }

    private void processDetection(
            DetectionTask task,
            List<Path> imagePaths,
            ModelInfo modelInfo,
            String outputFormat,
            Float confidenceThreshold
    ) throws IOException {
        float threshold = confidenceThreshold == null ? 0.5f : confidenceThreshold;
        int normalCount = 0;
        int bentCount = 0;
        int deformedCount = 0;
        int rustyCount = 0;
        int missingCount = 0;
        int compromisedCount = 0;
        int detectionInstancesCount = 0;
        int missedCount = 0;

        List<Map<String, Object>> perImageResults = new ArrayList<>();
        String resultOssPrefix = task.getResultOssPrefix();
        Path resultPath = Paths.get(resultOssPrefix);
        Path resultDir = Files.isDirectory(resultPath) ? resultPath : resultPath.getParent();
        String sourceOssPrefix = task.getSourceOssPrefix();
        Path annotatedDir = Paths.get(sourceOssPrefix.replace("images", "annotated"));
        Files.createDirectories(resultDir);
        Files.createDirectories(annotatedDir);

        for (Path imagePath : imagePaths) {
            ImageInferenceService.ClassificationResult result =
                    imageInferenceService.classify(imagePath, modelInfo.getModelPath());

            boolean detected = result.confidence() >= threshold;
            if (detected) {
                detectionInstancesCount++;
                switch (result.category()) {
                    case "Normal" -> normalCount++;
                    case "Bent" -> bentCount++;
                    case "Deformed" -> deformedCount++;
                    case "Rusty" -> rustyCount++;
                    case "Missing" -> missingCount++;
                    case "Compromised" -> compromisedCount++;
                    default -> {}
                }
            } else {
                missedCount++;
            }

            Path annotatedPath = annotatedDir.resolve(imagePath.getFileName().toString());
            imageInferenceService.renderAnnotatedImage(
                    imagePath,
                    detected ? result.category() : "UNKNOWN",
                    result.confidence(),
                    annotatedPath
            );

            Map<String, Object> imageResult = new LinkedHashMap<>();
            imageResult.put("fileName", imagePath.getFileName().toString());
            imageResult.put("category", result.category());
            imageResult.put("confidence", result.confidence());
            imageResult.put("detected", detected);
            imageResult.put("annotatedImage", annotatedPath.getFileName().toString());
            perImageResults.add(imageResult);

            if ("YOLO".equalsIgnoreCase(outputFormat)) {
                Path txtPath = resultDir.resolve(replaceExtension(imagePath.getFileName().toString(), ".txt"));
                String content = result.category() + " " + String.format(java.util.Locale.US, "%.6f", result.confidence());
                Files.writeString(txtPath, content + System.lineSeparator());
            }
        }

        if ("COCO".equalsIgnoreCase(outputFormat)) {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("modelId", modelInfo.getModelId());
            payload.put("outputType", "classification");
            payload.put("threshold", threshold);
            payload.put("images", perImageResults);
            objectMapper.writerWithDefaultPrettyPrinter().writeValue(resultPath.toFile(), payload);
        }

        // 构建 statistics_json
        Map<String, Object> classCounts = new LinkedHashMap<>();
        classCounts.put("Normal", normalCount);
        classCounts.put("Bent", bentCount);
        classCounts.put("Deformed", deformedCount);
        classCounts.put("Rusty", rustyCount);
        classCounts.put("Missing", missingCount);
        classCounts.put("Compromised", compromisedCount);

        Map<String, Object> statistics = new LinkedHashMap<>();
        statistics.put("classCounts", classCounts);
        statistics.put("missDetectionRate", imagePaths.isEmpty() ? 0.0 : missedCount * 100.0 / imagePaths.size());

        task.setStatisticsJson(objectMapper.writeValueAsString(statistics));
        task.setSuccessfulImages(detectionInstancesCount);
        task.setFailedImages(missedCount);
        task.setProcessedImages(imagePaths.size());
        task.setStatus("COMPLETED");
        task.setStage("COMPLETED");
        task.setFinishedAt(LocalDateTime.now());
        task.setUpdatedAt(LocalDateTime.now());
        detectionTaskMapper.updateById(task);
    }

    private String replaceExtension(String fileName, String newExtension) {
        int dotIndex = fileName.lastIndexOf('.');
        if (dotIndex < 0) {
            return fileName + newExtension;
        }
        return fileName.substring(0, dotIndex) + newExtension;
    }
}
