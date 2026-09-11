package com.ruanzhu.doorhandle.module.model.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.module.model.service.ModelInfoService;
import com.ruanzhu.doorhandle.module.model.service.ModelService;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.extern.slf4j.Slf4j;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

/**
 * 模型信息控制器
 */
@RestController
@RequestMapping("/api/model-info")
@Slf4j
@Validated
public class ModelInfoController {

    private final ModelInfoService modelInfoService;
    private final ModelService modelService;

    public ModelInfoController(ModelInfoService modelInfoService, ModelService modelService) {
        this.modelInfoService = modelInfoService;
        this.modelService = modelService;
    }

    /**
     * 分页查询模型信息
     */
    @GetMapping
    public Result<Page<ModelInfo>> getModelInfoPage(
            @RequestParam(defaultValue = "1") @Min(value = 1, message = "页码不能小于 1") Integer page,
            @RequestParam(defaultValue = "10") @Min(value = 1, message = "每页数量不能小于 1") @Max(value = 200, message = "每页数量不能超过 200") Integer size,
            @RequestParam(required = false) Integer modelId,
            @RequestParam(required = false) String modelName,
            @RequestParam(required = false) String version,
            @RequestParam(required = false) String status) {
        
        log.info("分页查询模型信息: page={}, size={}, modelId={}, modelName={}, version={}, status={}", page, size, modelId, modelName, version, status);
        Page<ModelInfo> pageResult = modelInfoService.getModelInfoPage(page, size, modelId, modelName, version, status);
        return Result.success(pageResult);
    }

    /**
     * 根据模型ID获取模型信息
     */
    @GetMapping("/{modelId}")
    public Result<ModelInfo> getModelInfoById(@PathVariable Integer modelId) {
        log.info("根据模型ID查询模型信息: modelId={}", modelId);

        ModelInfo modelInfo = modelInfoService.getModelInfoByModelId(modelId);
        if (modelInfo == null) {
            return Result.error(404, "模型信息不存在");
        }
        return Result.success(modelInfo);
    }

    /**
     * 新增模型信息
     */
    @PostMapping
    public Result<Void> saveModelInfo(@RequestBody ModelInfo modelInfo) {
        log.info("新增模型信息: {}", modelInfo);

        boolean success = modelInfoService.saveModelInfo(modelInfo);
        if (!success) {
            throw new BusinessException("新增模型信息失败");
        }
        return Result.success();
    }

    /**
     * 更新模型信息
     */
    @PutMapping("/{modelId}")
    public Result<Void> updateModelInfo(@PathVariable Integer modelId, @RequestBody ModelInfo modelInfo) {
        log.info("更新模型信息: modelId={}, modelInfo={}", modelId, modelInfo);

        modelInfo.setModelId(modelId);
        boolean success = modelInfoService.updateModelInfo(modelInfo);
        if (!success) {
            return Result.error(404, "模型信息不存在或更新失败");
        }
        return Result.success();
    }

    /**
     * 记录模型评估指标
     */
    @PostMapping("/{modelId}/evaluation")
    public Result<Void> recordEvaluation(@PathVariable Integer modelId, @RequestBody ModelInfo evaluation) {
        log.info("记录模型评估指标: modelId={}, evaluation={}", modelId, evaluation);

        boolean success = modelInfoService.recordEvaluation(modelId, evaluation);
        if (!success) {
            return Result.error(404, "模型不存在或评估记录失败");
        }
        return Result.success();
    }

    /**
     * 配置模型部署策略
     */
    @PostMapping("/{modelId}/rollout")
    public Result<Void> configureRollout(@PathVariable Integer modelId, @RequestBody ModelInfo rollout) {
        log.info("配置模型部署策略: modelId={}, rollout={}", modelId, rollout);

        boolean success = modelInfoService.configureRollout(
                modelId,
                rollout.getDeploymentStrategy(),
                rollout.getCanaryPercent(),
                rollout.getAbGroup(),
                rollout.getRollbackFromModelId()
        );
        if (!success) {
            return Result.error(404, "模型不存在或部署策略配置失败");
        }
        return Result.success();
    }

    /**
     * 快捷回滚到指定模型
     */
    @PostMapping("/{modelId}/rollback")
    public Result<Void> rollbackModel(@PathVariable Integer modelId, @RequestParam Integer targetModelId) {
        log.info("回滚模型: modelId={}, targetModelId={}", modelId, targetModelId);

        boolean success = modelInfoService.configureRollout(modelId, "ROLLBACK", 0, null, targetModelId);
        if (!success) {
            return Result.error(404, "模型不存在或回滚失败");
        }
        return Result.success();
    }

    /**
     * 删除模型信息
     */
    @DeleteMapping("/{modelId}")
    public Result<Void> deleteModelInfo(@PathVariable Integer modelId) {
        log.info("删除模型信息: modelId={}", modelId);

        modelService.deleteModel(modelId);
        return Result.success();
    }
} 
