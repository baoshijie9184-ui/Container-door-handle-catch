package com.ruanzhu.doorhandle.module.detection.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.dto.ImageDetectionResponse;
import com.ruanzhu.doorhandle.module.detection.dto.SingleImageDetectionResponse;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.model.mapper.ModelInfoMapper;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.detection.service.ImageDetectionService;
import com.ruanzhu.doorhandle.module.detection.service.ImageInferenceService;
import com.ruanzhu.doorhandle.module.model.service.ModelService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.multipart.MultipartFile;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Stream;

@Service
@RequiredArgsConstructor
@Slf4j
public class ImageDetectionServiceImpl implements ImageDetectionService {

    private final ModelInfoMapper modelInfoMapper;
    private final DetectionTaskMapper detectionTaskMapper;
    private final ObjectMapper objectMapper;
    private final ModelService modelService;
    private final ImageInferenceService imageInferenceService;
    private final ImageDetectionAsyncService imageDetectionAsyncService;
    private final DetectionTaskAccessPolicy detectionTaskAccessPolicy;

    @Value("${detection.upload-dir:${user.dir}/uploads/images}")
    private String imageUploadDir;

    @Value("${detection.result-dir:${user.dir}/uploads/results}")
    private String resultDir;

    @Value("${detection.annotated-dir:${user.dir}/uploads/annotated}")
    private String annotatedDir;

    @Value("${app.upload.dir:${user.dir}/uploads/images}")
    private String uploadDir;

    @Value("${app.models.dir:${user.dir}/uploads/models}")
    private String modelsDir;

    @Value("${app.default.model:}")
    private String defaultModelFile;

    @Value("${detection.max-images-per-batch:200}")
    private int maxImagesPerBatch;

    @Value("${detection.max-image-bytes:10485760}")
    private long maxImageBytes;

    @Override
    public ImageDetectionResponse processImageDetection(
            List<MultipartFile> files,
            Integer modelId,
            String outputFormat,
            Float confidenceThreshold
    ) {
        if (files == null || files.isEmpty()) {
            throw new BusinessException("上传图片不能为空");
        }
        validateBatchImages(files);
        if (!"YOLO".equalsIgnoreCase(outputFormat) && !"COCO".equalsIgnoreCase(outputFormat)) {
            throw new BusinessException("不支持的输出格式: " + outputFormat);
        }

        ModelInfo modelInfo = resolveModelInfo(modelId);
        String folderName = "detect_" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss"));
        Path imageFolderPath = Paths.get(imageUploadDir, folderName).toAbsolutePath().normalize();
        Path resultFolderPath = Paths.get(resultDir, folderName).toAbsolutePath().normalize();
        Path annotatedFolderPath = Paths.get(annotatedDir, folderName).toAbsolutePath().normalize();

        try {
            Files.createDirectories(imageFolderPath);
            Files.createDirectories(resultFolderPath);
            Files.createDirectories(annotatedFolderPath);
        } catch (IOException e) {
            throw new BusinessException("创建检测目录失败: " + e.getMessage());
        }

        List<Path> savedImagePaths = saveBatchImages(files, imageFolderPath);

        // 创建 detection_task 记录
        DetectionTask task = new DetectionTask();
        task.setTaskId(buildTaskId());
        task.setTaskType("BATCH_DIRECT");
        task.setStatus("PROCESSING");
        task.setStage("PROCESSING");
        task.setModelId(modelInfo.getModelId());
        task.setModelVersion(modelInfo.getVersion());
        task.setTotalImages(savedImagePaths.size());
        task.setProcessedImages(0);
        task.setSuccessfulImages(0);
        task.setFailedImages(0);
        task.setSourceOssPrefix(imageFolderPath.toString());
        task.setResultOssPrefix("YOLO".equalsIgnoreCase(outputFormat)
                ? resultFolderPath.toString()
                : resultFolderPath.resolve("result.json").toString());
        task.setThreshold(BigDecimal.valueOf(confidenceThreshold == null ? 0.5f : confidenceThreshold));
        task.setCreatedBy(currentUsername());
        task.setCreatedAt(LocalDateTime.now());
        task.setUpdatedAt(LocalDateTime.now());
        detectionTaskMapper.insert(task);
        if (modelInfo.getModelId() != null) {
            modelService.incrementUsageStats(modelInfo.getModelId(), LocalDateTime.now());
        }

        imageDetectionAsyncService.performDetectionAsync(
                task,
                savedImagePaths,
                modelInfo,
                outputFormat,
                confidenceThreshold
        );

        return ImageDetectionResponse.builder()
                .id(task.getId())
                .status("PROCESSING")
                .detectedImagesCount(savedImagePaths.size())
                .modelId(modelInfo.getModelId())
                .resultPath(task.getResultOssPrefix())
                .build();
    }

    @Override
    public List<DetectionTask> getAllDetectionData() {
        LambdaQueryWrapper<DetectionTask> wrapper = new LambdaQueryWrapper<>();
        Authentication authentication = currentAuthentication();
        detectionTaskAccessPolicy.assertAuthenticated(authentication);
        List<DetectionTask> tasks = detectionTaskMapper.selectList(wrapper);
        tasks.forEach(task -> detectionTaskAccessPolicy.assertCanAccess(task, authentication));
        return tasks;
    }

    @Override
    public DetectionTask getDetectionDataById(Long id) {
        DetectionTask task = detectionTaskMapper.selectById(id);
        if (task != null) {
            detectionTaskAccessPolicy.assertCanAccess(task, currentAuthentication());
        }
        return task;
    }

    @Override
    public void deleteDetectionData(Long id) {
        DetectionTask task = detectionTaskMapper.selectById(id);
        if (task == null) {
            throw new BusinessException("检测数据不存在");
        }
        detectionTaskAccessPolicy.assertCanAccess(task, currentAuthentication());
        if (task.getSourceOssPrefix() != null) {
            deleteRecursively(Paths.get(task.getSourceOssPrefix()));
        }
        if (task.getResultOssPrefix() != null) {
            deleteRecursively(Paths.get(task.getResultOssPrefix()));
        }
        if (task.getSourceOssPrefix() != null) {
            deleteRecursively(resolveAnnotatedPath(task.getSourceOssPrefix()));
        }
        detectionTaskMapper.deleteById(id);
    }

    @Override
    public SingleImageDetectionResponse detectImage(MultipartFile imageFile, Integer modelId) {
        if (imageFile == null || imageFile.isEmpty()) {
            return SingleImageDetectionResponse.builder()
                    .errorMessage("请上传有效的图像文件")
                    .build();
        }
        String imageValidationError = validateImageFile(imageFile);
        if (imageValidationError != null) {
            return SingleImageDetectionResponse.builder()
                    .errorMessage(imageValidationError)
                    .build();
        }

        try {
            ModelInfo modelInfo = resolveModelInfo(modelId);
            String folderName = "detect_" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss"));
            Path uploadPath = Paths.get(uploadDir, folderName).toAbsolutePath().normalize();
            Path annotatedPath = Paths.get(annotatedDir, folderName).toAbsolutePath().normalize();
            Files.createDirectories(uploadPath);
            Files.createDirectories(annotatedPath);

            String savedFileName = UUID.randomUUID() + getExtension(imageFile.getOriginalFilename(), ".jpg");
            Path filePath = uploadPath.resolve(savedFileName);
            imageFile.transferTo(filePath.toFile());

            ImageInferenceService.ClassificationResult result =
                    imageInferenceService.classify(filePath, modelInfo.getModelPath());

            String annotatedFileName = "annotated_" + savedFileName;
            Path annotatedFilePath = annotatedPath.resolve(annotatedFileName);
            imageInferenceService.renderAnnotatedImage(
                    filePath,
                    result.category(),
                    result.confidence(),
                    annotatedFilePath
            );

            // 将单图检测结果写入 detection_task 表
            Map<String, Object> classCounts = new LinkedHashMap<>();
            classCounts.put("Normal", "Normal".equals(result.category()) ? 1 : 0);
            classCounts.put("Bent", "Bent".equals(result.category()) ? 1 : 0);
            classCounts.put("Deformed", "Deformed".equals(result.category()) ? 1 : 0);
            classCounts.put("Rusty", "Rusty".equals(result.category()) ? 1 : 0);
            classCounts.put("Missing", "Missing".equals(result.category()) ? 1 : 0);
            classCounts.put("Compromised", "Compromised".equals(result.category()) ? 1 : 0);

            Map<String, Object> statistics = new LinkedHashMap<>();
            statistics.put("classCounts", classCounts);
            statistics.put("missDetectionRate", result.confidence() < 0.5 ? 100.0 : 0.0);

            DetectionTask task = new DetectionTask();
            task.setTaskId(buildTaskId());
            task.setTaskType("SINGLE");
            task.setStatus("COMPLETED");
            task.setStage("COMPLETED");
            task.setModelId(modelInfo.getModelId());
            task.setModelVersion(modelInfo.getVersion());
            task.setTotalImages(1);
            boolean detected = result.confidence() >= 0.5f;
            task.setSuccessfulImages(detected ? 1 : 0);
            task.setFailedImages(detected ? 0 : 1);
            task.setSourceOssPrefix(uploadPath.toString());
            task.setResultOssPrefix(annotatedPath.toString());
            task.setThreshold(BigDecimal.valueOf(0.5f));
            task.setCreatedBy(currentUsername());
            task.setStatisticsJson(objectMapper.writeValueAsString(statistics));
            task.setCreatedAt(LocalDateTime.now());
            task.setFinishedAt(LocalDateTime.now());
            task.setUpdatedAt(LocalDateTime.now());
            detectionTaskMapper.insert(task);
            if (modelInfo.getModelId() != null) {
                modelService.incrementUsageStats(modelInfo.getModelId(), LocalDateTime.now());
            }

            return SingleImageDetectionResponse.builder()
                    .category(result.category())
                    .confidence(result.confidence())
                    .processedImagePath("/api/direct/images/" + folderName + "/" + savedFileName)
                    .annotatedImagePath("/api/direct/annotated/" + folderName + "/" + annotatedFileName)
                    .build();
        } catch (Exception e) {
            log.error("单图检测失败", e);
            return SingleImageDetectionResponse.builder()
                    .errorMessage("检测失败: " + e.getMessage())
                    .build();
        }
    }

    private String buildTaskId() {
        return "det_" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss"))
                + "_" + UUID.randomUUID().toString().replace("-", "").substring(0, 8);
    }

    private Authentication currentAuthentication() {
        return SecurityContextHolder.getContext().getAuthentication();
    }

    private String currentUsername() {
        Authentication authentication = currentAuthentication();
        return authentication == null ? null : authentication.getName();
    }

    private List<Path> saveBatchImages(List<MultipartFile> files, Path imageFolderPath) {
        List<Path> savedImagePaths = new ArrayList<>();
        for (MultipartFile file : files) {
            try {
                String targetName = UUID.randomUUID() + getExtension(file.getOriginalFilename(), ".jpg");
                Path targetPath = imageFolderPath.resolve(targetName);
                file.transferTo(targetPath.toFile());
                savedImagePaths.add(targetPath);
            } catch (IOException e) {
                throw new BusinessException("保存图片失败: " + e.getMessage());
            }
        }
        return savedImagePaths;
    }

    private void validateBatchImages(List<MultipartFile> files) {
        if (files.size() > maxImagesPerBatch) {
            throw new BusinessException("单次最多上传 " + maxImagesPerBatch + " 张图片");
        }
        for (MultipartFile file : files) {
            String error = validateImageFile(file);
            if (error != null) {
                throw new BusinessException(error);
            }
        }
    }

    private String validateImageFile(MultipartFile file) {
        if (file == null || file.isEmpty()) {
            return "上传图片不能为空";
        }
        if (file.getSize() > maxImageBytes) {
            return "图片文件不能超过 " + formatBytes(maxImageBytes);
        }
        String originalFilename = file.getOriginalFilename();
        String extension = getExtension(originalFilename, "");
        if (!List.of(".jpg", ".jpeg", ".png", ".bmp").contains(extension)) {
            return "仅支持 JPG、PNG、BMP 图片";
        }
        String contentType = file.getContentType();
        if (contentType != null && !contentType.isBlank()
                && !"application/octet-stream".equalsIgnoreCase(contentType)
                && !List.of("image/jpeg", "image/png", "image/bmp", "image/x-ms-bmp").contains(contentType.toLowerCase(Locale.ROOT))) {
            return "图片 Content-Type 不受支持: " + contentType;
        }
        return null;
    }

    private String formatBytes(long bytes) {
        if (bytes >= 1024L * 1024L) {
            return (bytes / 1024L / 1024L) + "MB";
        }
        if (bytes >= 1024L) {
            return (bytes / 1024L) + "KB";
        }
        return bytes + "B";
    }

    private ModelInfo resolveModelInfo(Integer modelId) {
        if (modelId != null) {
            ModelInfo modelInfo = modelInfoMapper.selectByModelId(modelId);
            if (modelInfo == null) {
                throw new BusinessException("所选模型不存在");
            }
            return modelInfo;
        }

        if (defaultModelFile != null && !defaultModelFile.isBlank()) {
            Path defaultModelPath = Paths.get(modelsDir, defaultModelFile);
            if (Files.exists(defaultModelPath)) {
                ModelInfo modelInfo = new ModelInfo();
                modelInfo.setModelId(null);
                modelInfo.setModelName(defaultModelFile);
                modelInfo.setModelPath(defaultModelPath.toString());
                return modelInfo;
            }
        }

        List<ModelInfo> allModels = modelService.getAllModels();
        if (allModels == null || allModels.isEmpty()) {
            throw new BusinessException("没有可用的模型");
        }
        return allModels.stream()
                .filter(model -> Boolean.TRUE.equals(model.getIsDefault()))
                .findFirst()
                .orElseGet(() -> allModels.stream()
                        .filter(model -> "PUBLISHED".equals(model.getStatus()))
                        .findFirst()
                        .orElse(allModels.get(0)));
    }

    private Path resolveAnnotatedPath(String sourceOssPrefix) {
        return Paths.get(sourceOssPrefix.replace("images", "annotated"));
    }

    private void deleteRecursively(Path path) {
        try {
            if (path == null || !Files.exists(path)) {
                return;
            }
            if (Files.isDirectory(path)) {
                try (Stream<Path> stream = Files.walk(path)) {
                    stream.sorted(Comparator.reverseOrder())
                            .map(Path::toFile)
                            .forEach(File::delete);
                }
            } else {
                Files.deleteIfExists(path);
            }
        } catch (IOException e) {
            log.warn("删除路径失败: {}", path, e);
        }
    }

    private String getExtension(String originalFilename, String fallbackExtension) {
        if (originalFilename == null) {
            return fallbackExtension;
        }
        int dotIndex = originalFilename.lastIndexOf('.');
        if (dotIndex < 0) {
            return fallbackExtension;
        }
        return originalFilename.substring(dotIndex).toLowerCase(Locale.ROOT);
    }
}
