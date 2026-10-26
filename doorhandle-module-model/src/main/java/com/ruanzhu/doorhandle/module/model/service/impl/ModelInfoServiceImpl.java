package com.ruanzhu.doorhandle.module.model.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.module.model.mapper.ModelInfoMapper;
import com.ruanzhu.doorhandle.module.model.service.ModelInfoService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.util.Set;

/**
 * 模型信息服务实现类
 */
@Service
@Slf4j
public class ModelInfoServiceImpl extends ServiceImpl<ModelInfoMapper, ModelInfo> implements ModelInfoService {

    @org.springframework.beans.factory.annotation.Autowired
    private com.ruanzhu.doorhandle.module.model.service.ModelService modelService;
    @org.springframework.beans.factory.annotation.Autowired
    private com.ruanzhu.doorhandle.module.model.service.ModelUploadFiles uploadFiles;

    private static final Set<String> SUPPORTED_DEPLOYMENT_STRATEGIES = Set.of("FULL", "CANARY", "AB_TEST", "ROLLBACK");

    @Override
    public Page<ModelInfo> getModelInfoPage(Integer page, Integer size, Integer modelId, String modelName, String version, String status) {
        log.info("分页查询模型信息: page={}, size={}, modelId={}, modelName={}, version={}, status={}", page, size, modelId, modelName, version, status);
        
        Page<ModelInfo> pageParam = new Page<>(page, size);
        LambdaQueryWrapper<ModelInfo> queryWrapper = new LambdaQueryWrapper<>();
        
        // 添加查询条件
        if (modelId != null) {
            queryWrapper.eq(ModelInfo::getModelId, modelId);
        }
        
        if (StringUtils.hasText(modelName)) {
            queryWrapper.like(ModelInfo::getModelName, modelName);
        }
        
        if (StringUtils.hasText(version)) {
            queryWrapper.like(ModelInfo::getVersion, version);
        }
        if (StringUtils.hasText(status)) {
            queryWrapper.eq(ModelInfo::getStatus, status);
        }
        
        // 按上传时间降序排序
        queryWrapper.orderByDesc(ModelInfo::getUploadTime);
        
        return page(pageParam, queryWrapper);
    }

    @Override
    @Cacheable(cacheNames = "model", key = "'metadata:' + #modelId", unless = "#result == null")
    public ModelInfo getModelInfoByModelId(Integer modelId) {
        log.info("根据模型ID查询模型信息: modelId={}", modelId);
        LambdaQueryWrapper<ModelInfo> queryWrapper = new LambdaQueryWrapper<>();
        queryWrapper.eq(ModelInfo::getModelId, modelId);
        return getOne(queryWrapper);
    }

    @Override
    @CacheEvict(cacheNames = {"model", "dashboard"}, allEntries = true)
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DETECTION_MODEL",action="saveModelInfo",supervisorOnly=true)
    public boolean saveModelInfo(ModelInfo modelInfo) {
        log.info("保存模型信息: modelId={}", modelInfo.getModelId());
        validateModelFacts(modelInfo);
        uploadFiles.metadataPath(modelInfo.getModelPath(),null);
        return save(modelInfo);
    }

    @Override
    @CacheEvict(cacheNames = {"model", "dashboard"}, allEntries = true)
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DETECTION_MODEL",action="updateModelInfo",supervisorOnly=true)
    public boolean updateModelInfo(ModelInfo modelInfo) {
        log.info("更新模型信息: modelId={}", modelInfo.getModelId());
        ModelInfo existing = getModelInfoByModelId(modelInfo.getModelId());
        if (existing == null) {
            return false;
        }

        uploadFiles.metadataPath(modelInfo.getModelPath(),existing.getModelPath());
        mergeEditableFields(existing, modelInfo);
        validateModelFacts(existing);
        return updateById(existing);
    }

    @Override
    @CacheEvict(cacheNames = {"model", "dashboard"}, allEntries = true)
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DETECTION_MODEL",action="RECORD_EVALUATION",supervisorOnly=true)
    public boolean recordEvaluation(Integer modelId, ModelInfo evaluation) {
        log.info("记录模型评估指标: modelId={}, evaluation={}", modelId, evaluation);
        ModelInfo existing = getModelInfoByModelId(modelId);
        if (existing == null) {
            return false;
        }

        validateMetric(evaluation.getPrecisionScore());
        validateMetric(evaluation.getRecallScore());
        validateMetric(evaluation.getMapScore());
        validateMetric(evaluation.getF1Score());
        if (evaluation.getAvgInferenceMs() != null && evaluation.getAvgInferenceMs() < 0) {
            throw new BusinessException("平均推理耗时不能为负数");
        }

        // Old clients omit these fields. Preserve their existing facts rather than silently erasing them.
        mergeModelFacts(existing, evaluation);

        existing.setEvaluationDataset(evaluation.getEvaluationDataset());
        existing.setPrecisionScore(evaluation.getPrecisionScore());
        existing.setRecallScore(evaluation.getRecallScore());
        existing.setMapScore(evaluation.getMapScore());
        existing.setF1Score(evaluation.getF1Score());
        existing.setAvgInferenceMs(evaluation.getAvgInferenceMs());
        if (evaluation.getCompatibilityNote() != null) existing.setCompatibilityNote(evaluation.getCompatibilityNote());
        validateModelFacts(existing);
        existing.setMlopsStatus("EVALUATED");
        return updateById(existing);
    }

    @Override
    @CacheEvict(cacheNames = {"model", "dashboard"}, allEntries = true)
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DETECTION_MODEL",action="CONFIGURE_ROLLOUT",supervisorOnly=true)
    public boolean configureRollout(Integer modelId, String deploymentStrategy, Integer canaryPercent,
                                    String abGroup, Integer rollbackFromModelId) {
        log.info("配置模型部署策略: modelId={}, strategy={}, canaryPercent={}, abGroup={}, rollbackFrom={}",
                modelId, deploymentStrategy, canaryPercent, abGroup, rollbackFromModelId);
        ModelInfo existing = getModelInfoByModelId(modelId);
        if (existing == null) {
            return false;
        }

        String normalizedStrategy = StringUtils.hasText(deploymentStrategy)
                ? deploymentStrategy.toUpperCase()
                : "FULL";
        if (!SUPPORTED_DEPLOYMENT_STRATEGIES.contains(normalizedStrategy)) {
            throw new BusinessException("不支持的部署策略: " + normalizedStrategy);
        }
        int safePercent = canaryPercent == null ? 100 : Math.max(0, Math.min(100, canaryPercent));
        if ("ROLLBACK".equals(normalizedStrategy) && rollbackFromModelId == null) {
            throw new BusinessException("回滚策略必须指定来源模型");
        }
        if ("ROLLBACK".equals(normalizedStrategy)) {
            ModelInfo rollbackSource = getModelInfoByModelId(rollbackFromModelId);
            if (rollbackSource == null) {
                throw new BusinessException("回滚来源模型不存在");
            }
            if (!"PUBLISHED".equals(rollbackSource.getStatus())) {
                throw new BusinessException("只能回滚到已发布模型");
            }
        }

        existing.setDeploymentStrategy(normalizedStrategy);
        existing.setCanaryPercent(safePercent);
        existing.setAbGroup(abGroup);
        existing.setRollbackFromModelId(rollbackFromModelId);
        existing.setMlopsStatus("ROLLBACK".equals(normalizedStrategy) ? "ROLLED_BACK" : "ROLLOUT");
        return updateById(existing);
    }

    private void validateMetric(BigDecimal value) {
        if (value == null) {
            return;
        }
        if (value.compareTo(BigDecimal.ZERO) < 0 || value.compareTo(BigDecimal.ONE) > 0) {
            throw new BusinessException("模型评估指标必须在 0 到 1 之间");
        }
    }

    private void mergeModelFacts(ModelInfo target, ModelInfo incoming) {
        if (incoming.getTrainingImageCount() != null) target.setTrainingImageCount(incoming.getTrainingImageCount());
        if (incoming.getTrainingCompletedAt() != null) target.setTrainingCompletedAt(incoming.getTrainingCompletedAt());
        if (incoming.getEvaluationImageCount() != null) target.setEvaluationImageCount(incoming.getEvaluationImageCount());
        if (incoming.getNoDetectionImageCount() != null) target.setNoDetectionImageCount(incoming.getNoDetectionImageCount());
        if (incoming.getInferenceFps() != null) target.setInferenceFps(incoming.getInferenceFps());
    }

    private void validateModelFacts(ModelInfo model) {
        validateMetric(model.getMapScore());
        if (model.getTrainingImageCount() != null && model.getTrainingImageCount() <= 0)
            throw new BusinessException("训练图片数量必须为正整数，未知请留空");
        Integer images = model.getEvaluationImageCount(), empty = model.getNoDetectionImageCount();
        if ((images == null) != (empty == null)) throw new BusinessException("成功评估图片数和整图未检出图片数必须同时登记");
        if (images != null && (images < 0 || empty < 0 || empty > images))
            throw new BusinessException("整图未检出图片数必须在 0 到成功评估图片数之间");
        BigDecimal fps = model.getInferenceFps();
        if (fps != null && (fps.signum() <= 0 || fps.compareTo(new BigDecimal("99999999.9999")) > 0
                || fps.stripTrailingZeros().scale() > 4))
            throw new BusinessException("每秒检测图片速度必须大于 0，最多保留四位小数");
        if (fps != null && !StringUtils.hasText(model.getCompatibilityNote()))
            throw new BusinessException("登记实测 FPS 时请注明设备、CPU/GPU、输入尺寸、批大小和计时范围");
        if (model.getCompatibilityNote() != null && model.getCompatibilityNote().length() > 500)
            throw new BusinessException("测试环境说明不能超过 500 字");
    }

    @Override
    @CacheEvict(cacheNames = {"model", "dashboard"}, allEntries = true)
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DETECTION_MODEL",action="deleteModelInfoByModelId",supervisorOnly=true)
    public boolean deleteModelInfoByModelId(Integer modelId) {
        log.info("删除模型信息: modelId={}", modelId);
        if(baseMapper.selectByModelId(modelId)==null) return false;
        modelService.deleteModel(modelId);
        return true;
    }

    private void mergeEditableFields(ModelInfo existing, ModelInfo incoming) {
        mergeModelFacts(existing, incoming);
        if (incoming.getModelName() != null) {
            existing.setModelName(incoming.getModelName());
        }
        if (incoming.getVersion() != null) {
            existing.setVersion(incoming.getVersion());
        }
        if (incoming.getModelPath() != null) {
            existing.setModelPath(incoming.getModelPath());
        }
        if (incoming.getUploadTime() != null) {
            existing.setUploadTime(incoming.getUploadTime());
        }
        if (incoming.getUpdateDescription() != null) {
            existing.setUpdateDescription(incoming.getUpdateDescription());
        }
        if (incoming.getStatus() != null) {
            existing.setStatus(incoming.getStatus());
        }
        if (incoming.getIsDefault() != null) {
            existing.setIsDefault(incoming.getIsDefault());
        }
        if (incoming.getCreator() != null) {
            existing.setCreator(incoming.getCreator());
        }
        if (incoming.getPublishedAt() != null) {
            existing.setPublishedAt(incoming.getPublishedAt());
        }
        if (incoming.getLastUsedAt() != null) {
            existing.setLastUsedAt(incoming.getLastUsedAt());
        }
        if (incoming.getUsageCount() != null) {
            existing.setUsageCount(incoming.getUsageCount());
        }
        if (incoming.getValidationStatus() != null) {
            existing.setValidationStatus(incoming.getValidationStatus());
        }
        if (incoming.getValidationMessage() != null) {
            existing.setValidationMessage(incoming.getValidationMessage());
        }
        if (incoming.getMlopsStatus() != null) {
            existing.setMlopsStatus(incoming.getMlopsStatus());
        }
        if (incoming.getEvaluationDataset() != null) {
            existing.setEvaluationDataset(incoming.getEvaluationDataset());
        }
        if (incoming.getPrecisionScore() != null) {
            existing.setPrecisionScore(incoming.getPrecisionScore());
        }
        if (incoming.getRecallScore() != null) {
            existing.setRecallScore(incoming.getRecallScore());
        }
        if (incoming.getMapScore() != null) {
            existing.setMapScore(incoming.getMapScore());
        }
        if (incoming.getF1Score() != null) {
            existing.setF1Score(incoming.getF1Score());
        }
        if (incoming.getAvgInferenceMs() != null) {
            existing.setAvgInferenceMs(incoming.getAvgInferenceMs());
        }
        if (incoming.getCompatibilityNote() != null) {
            existing.setCompatibilityNote(incoming.getCompatibilityNote());
        }
        if (incoming.getDeploymentStrategy() != null) {
            existing.setDeploymentStrategy(incoming.getDeploymentStrategy());
        }
        if (incoming.getCanaryPercent() != null) {
            existing.setCanaryPercent(incoming.getCanaryPercent());
        }
        if (incoming.getAbGroup() != null) {
            existing.setAbGroup(incoming.getAbGroup());
        }
        if (incoming.getRollbackFromModelId() != null) {
            existing.setRollbackFromModelId(incoming.getRollbackFromModelId());
        }
    }
} 
