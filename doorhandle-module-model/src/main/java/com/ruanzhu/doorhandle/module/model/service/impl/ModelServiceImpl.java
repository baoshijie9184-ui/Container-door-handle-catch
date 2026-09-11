package com.ruanzhu.doorhandle.module.model.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.module.model.entity.ModelOperationLog;
import com.ruanzhu.doorhandle.module.model.mapper.ModelInfoMapper;
import com.ruanzhu.doorhandle.module.model.mapper.ModelOperationLogMapper;
import com.ruanzhu.doorhandle.module.model.service.ModelService;
import com.ruanzhu.doorhandle.module.model.service.ModelValidationService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

import java.io.File;
import java.io.IOException;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

@Service
@RequiredArgsConstructor
@Slf4j
public class ModelServiceImpl implements ModelService {

    private final ModelInfoMapper modelInfoMapper;
    private final ModelOperationLogMapper modelOperationLogMapper;
    private final ModelValidationService modelValidationService;

    @Value("${model.upload-dir:${user.dir}/uploads/models}")
    private String modelUploadDir;

    @Value("${model.max-upload-bytes:209715200}")
    private long maxUploadBytes;

    @Override
    public ModelInfo uploadModel(MultipartFile file, String modelName, String version, String updateDescription) {
        if (file == null || file.isEmpty()) {
            throw new BusinessException("上传文件不能为空");
        }
        validateOnnxFile(file);

        ModelInfo existingModel = modelInfoMapper.selectByModelNameAndVersion(modelName, version);
        if (existingModel != null) {
            throw new BusinessException("模型名称和版本已存在");
        }

        File modelDir = new File(modelUploadDir);
        if (!modelDir.exists() && !modelDir.mkdirs()) {
            throw new BusinessException("创建模型目录失败");
        }

        File destFile = null;
        try {
            String originalFilename = file.getOriginalFilename();
            String fileExtension = originalFilename != null && originalFilename.contains(".")
                    ? originalFilename.substring(originalFilename.lastIndexOf("."))
                    : ".onnx";
            String savedFilename = UUID.randomUUID() + fileExtension;
            destFile = new File(modelDir, savedFilename);
            file.transferTo(destFile);

            ModelInfo insertedModel = insertWithRetry(modelName, version, updateDescription, destFile);

            LambdaQueryWrapper<ModelInfo> queryWrapper = new LambdaQueryWrapper<>();
            queryWrapper.eq(ModelInfo::getModelId, insertedModel.getModelId());
            ModelInfo savedModel = modelInfoMapper.selectOne(queryWrapper);
            if (savedModel == null) {
                throw new BusinessException("模型信息保存失败");
            }

            savedModel.setUploadTime(LocalDateTime.now());
            modelInfoMapper.updateModelRecord(savedModel);
            return savedModel;
        } catch (IOException e) {
            deleteQuietly(destFile);
            throw new BusinessException("保存模型文件失败: " + e.getMessage());
        } catch (RuntimeException e) {
            deleteQuietly(destFile);
            throw e;
        }
    }

    private ModelInfo insertWithRetry(String modelName, String version, String updateDescription, File destFile) {
        DuplicateKeyException lastException = null;
        ModelValidationService.ValidationResult validationResult = modelValidationService.validate(destFile.toPath());
        for (int attempt = 0; attempt < 3; attempt++) {
            ModelInfo modelInfo = new ModelInfo();
            modelInfo.setModelId(modelInfoMapper.selectNextModelId());
            modelInfo.setModelName(modelName);
            modelInfo.setVersion(version);
            modelInfo.setModelPath(destFile.getAbsolutePath());
            modelInfo.setUploadTime(LocalDateTime.now());
            modelInfo.setUpdateDescription(updateDescription);
            modelInfo.setStatus("PASSED".equals(validationResult.status()) ? "READY" : "DRAFT");
            modelInfo.setIsDefault(Boolean.FALSE);
            modelInfo.setCreator(resolveCurrentUsername());
            modelInfo.setUsageCount(0);
            modelInfo.setValidationStatus(validationResult.status());
            modelInfo.setValidationMessage(validationResult.message());
            modelInfo.setMlopsStatus("UNASSESSED");
            modelInfo.setDeploymentStrategy("FULL");
            modelInfo.setCanaryPercent(100);
            try {
                modelInfoMapper.insert(modelInfo);
                recordOperation(
                        modelInfo.getModelId(),
                        "UPLOAD",
                        "上传模型: " + modelName + "@" + version + "，校验结果: " + validationResult.status()
                );
                return modelInfo;
            } catch (DuplicateKeyException e) {
                lastException = e;
                log.warn("model_id 冲突，重试第 {} 次: {}", attempt + 1, e.getMessage());
            }
        }
        throw new BusinessException("模型信息保存失败: " + (lastException != null ? lastException.getMessage() : "model_id 冲突"));
    }

    @Override
    public ModelInfo updateModel(ModelInfo modelInfo) {
        LambdaQueryWrapper<ModelInfo> queryWrapper = new LambdaQueryWrapper<>();
        queryWrapper.eq(ModelInfo::getModelId, modelInfo.getModelId());
        ModelInfo existingModel = modelInfoMapper.selectOne(queryWrapper);

        if (existingModel == null) {
            throw new BusinessException("要更新的模型不存在");
        }

        existingModel.setUpdateDescription(modelInfo.getUpdateDescription());

        modelInfoMapper.updateModelRecord(existingModel);
        return existingModel;
    }

    @Override
    public void deleteModel(Integer modelId) {
        LambdaQueryWrapper<ModelInfo> queryWrapper = new LambdaQueryWrapper<>();
        queryWrapper.eq(ModelInfo::getModelId, modelId);

        ModelInfo modelInfo = modelInfoMapper.selectOne(queryWrapper);
        if (modelInfo == null) {
            throw new BusinessException("要删除的模型不存在");
        }
        if (defaultInt(modelInfo.getUsageCount()) > 0) {
            throw new BusinessException("已被任务引用的模型不允许删除，请改为停用或归档");
        }

        String modelPath = modelInfo.getModelPath();
        if (StringUtils.hasText(modelPath)) {
            File modelFile = new File(modelPath);
            if (modelFile.exists() && !modelFile.delete()) {
                log.warn("模型文件删除失败: {}", modelPath);
            }
        }

        LambdaUpdateWrapper<ModelInfo> deleteWrapper = new LambdaUpdateWrapper<>();
        deleteWrapper.eq(ModelInfo::getModelId, modelId);
        modelInfoMapper.delete(deleteWrapper);
        recordOperation(modelId, "DELETE", "删除模型文件与记录");
    }

    @Override
    public List<ModelInfo> getAllModels() {
        return modelInfoMapper.selectAll();
    }

    @Override
    public ModelInfo publishModel(Integer modelId) {
        ModelInfo modelInfo = requireModel(modelId);
        if ("ARCHIVED".equals(modelInfo.getStatus())) {
            throw new BusinessException("已归档模型不能直接发布");
        }
        if (!"PASSED".equals(modelInfo.getValidationStatus())) {
            throw new BusinessException("模型校验未通过，不能发布");
        }
        if (!"READY".equals(modelInfo.getStatus()) && !"PUBLISHED".equals(modelInfo.getStatus())) {
            throw new BusinessException("只有就绪模型才能发布");
        }
        modelInfo.setStatus("PUBLISHED");
        if (modelInfo.getPublishedAt() == null) {
            modelInfo.setPublishedAt(LocalDateTime.now());
        }
        saveModel(modelInfo);
        recordOperation(modelId, "PUBLISH", "发布模型");
        return modelInfo;
    }

    @Override
    public ModelInfo setDefaultModel(Integer modelId) {
        ModelInfo modelInfo = requireModel(modelId);
        if (!"PUBLISHED".equals(modelInfo.getStatus())) {
            throw new BusinessException("只有已发布模型才能设为默认");
        }

        clearDefaultFlag();
        modelInfo.setIsDefault(Boolean.TRUE);
        saveModel(modelInfo);
        recordOperation(modelId, "SET_DEFAULT", "设为默认模型");
        return modelInfo;
    }

    @Override
    public ModelInfo disableModel(Integer modelId) {
        ModelInfo modelInfo = requireModel(modelId);
        modelInfo.setStatus("DISABLED");
        modelInfo.setIsDefault(Boolean.FALSE);
        saveModel(modelInfo);
        recordOperation(modelId, "DISABLE", "停用模型");
        return modelInfo;
    }

    @Override
    public ModelInfo archiveModel(Integer modelId) {
        ModelInfo modelInfo = requireModel(modelId);
        modelInfo.setStatus("ARCHIVED");
        modelInfo.setIsDefault(Boolean.FALSE);
        saveModel(modelInfo);
        recordOperation(modelId, "ARCHIVE", "归档模型");
        return modelInfo;
    }

    @Override
    public ModelInfo validateModel(Integer modelId) {
        ModelInfo modelInfo = requireModel(modelId);
        if (!StringUtils.hasText(modelInfo.getModelPath())) {
            throw new BusinessException("模型文件路径为空，不能校验");
        }

        ModelValidationService.ValidationResult validationResult = modelValidationService.validate(Path.of(modelInfo.getModelPath()));
        modelInfo.setValidationStatus(validationResult.status());
        modelInfo.setValidationMessage(validationResult.message());
        if ("PASSED".equals(validationResult.status())) {
            if (!"PUBLISHED".equals(modelInfo.getStatus())) {
                modelInfo.setStatus("READY");
            }
        } else {
            modelInfo.setStatus("DRAFT");
            modelInfo.setIsDefault(Boolean.FALSE);
        }
        saveModel(modelInfo);
        recordOperation(modelId, "VALIDATE", "重新校验模型，结果: " + validationResult.status());
        return modelInfo;
    }

    @Override
    public void incrementUsageStats(Integer modelId, LocalDateTime usedAt) {
        if (modelId == null) {
            return;
        }
        ModelInfo modelInfo = requireModel(modelId);
        modelInfo.setUsageCount(defaultInt(modelInfo.getUsageCount()) + 1);
        modelInfo.setLastUsedAt(usedAt != null ? usedAt : LocalDateTime.now());
        saveModel(modelInfo);
    }

    @Override
    public List<ModelOperationLog> getOperationLogs(Integer modelId) {
        return modelOperationLogMapper.selectByModelId(modelId);
    }

    private void validateOnnxFile(MultipartFile file) {
        String originalFilename = file.getOriginalFilename();
        if (originalFilename == null || !originalFilename.toLowerCase(Locale.ROOT).endsWith(".onnx")) {
            throw new BusinessException("仅支持上传 ONNX 格式文件");
        }
        if (file.getSize() > maxUploadBytes) {
            throw new BusinessException("模型文件不能超过 " + formatBytes(maxUploadBytes));
        }
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

    private void deleteQuietly(File file) {
        if (file == null || !file.exists()) {
            return;
        }
        if (!file.delete()) {
            log.warn("清理模型临时文件失败: {}", file.getAbsolutePath());
        }
    }

    private ModelInfo requireModel(Integer modelId) {
        LambdaQueryWrapper<ModelInfo> queryWrapper = new LambdaQueryWrapper<>();
        queryWrapper.eq(ModelInfo::getModelId, modelId);
        ModelInfo modelInfo = modelInfoMapper.selectOne(queryWrapper);
        if (modelInfo == null) {
            throw new BusinessException("模型不存在");
        }
        return modelInfo;
    }

    private void clearDefaultFlag() {
        List<ModelInfo> models = modelInfoMapper.selectAll();
        if (models == null) {
            return;
        }
        for (ModelInfo existing : models) {
            if (Boolean.TRUE.equals(existing.getIsDefault())) {
                existing.setIsDefault(Boolean.FALSE);
                saveModel(existing);
            }
        }
    }

    private void saveModel(ModelInfo modelInfo) {
        modelInfoMapper.updateModelRecord(modelInfo);
    }

    private void recordOperation(Integer modelId, String operationType, String remark) {
        if (modelId == null) {
            return;
        }
        ModelOperationLog logEntry = new ModelOperationLog();
        logEntry.setModelId(modelId);
        logEntry.setOperationType(operationType);
        logEntry.setOperator(resolveCurrentUsername());
        logEntry.setOperationTime(LocalDateTime.now());
        logEntry.setRemark(remark);
        try {
            modelOperationLogMapper.insert(logEntry);
        } catch (RuntimeException e) {
            log.warn("模型操作日志记录失败: modelId={}, operationType={}", modelId, operationType, e);
        }
    }

    private String resolveCurrentUsername() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || !StringUtils.hasText(authentication.getName())) {
            return "system";
        }
        return authentication.getName();
    }

    private int defaultInt(Integer value) {
        return value == null ? 0 : value;
    }
}
