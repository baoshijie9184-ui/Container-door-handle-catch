package com.ruanzhu.doorhandle.module.model.controller;

import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.module.model.entity.ModelOperationLog;
import com.ruanzhu.doorhandle.module.model.service.ModelService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.security.access.prepost.PreAuthorize;

import java.util.List;

/**
 * 模型管理控制器
 */
@RestController
@RequestMapping("/api/models")
@RequiredArgsConstructor
@Slf4j
public class ModelController {

    private final ModelService modelService;

    /**
     * 上传 ONNX 模型
     *
     * @param file              模型文件
     * @param modelName         模型名称
     * @param version           版本号
     * @param updateDescription 更新说明
     * @return 上传结果
     */
    @PostMapping("/upload")
    @PreAuthorize("hasRole('SUPERVISOR')")
    public Result<ModelInfo> uploadModel(
            @RequestParam("file") MultipartFile file,
            @RequestParam("modelName") String modelName,
            @RequestParam("version") String version,
            @RequestParam(value = "updateDescription", required = false) String updateDescription) {
        log.info("接收到模型上传请求: 文件名={}, 大小={}, 模型名={}, 版本={}", 
                file.getOriginalFilename(), file.getSize(), modelName, version);
        
        try {
            ModelInfo modelInfo = modelService.uploadModel(file, modelName, version, updateDescription);
            log.info("模型上传成功: ID={}, 路径={}", modelInfo.getModelId(), modelInfo.getModelPath());
            return Result.success(modelInfo);
        } catch (Exception e) {
            log.error("模型上传处理异常: {}", e.getMessage(), e);
            return Result.error(500, "模型上传失败: " + e.getMessage());
        }
    }

    /**
     * 更新 ONNX 模型信息
     *
     * @param modelInfo 模型信息
     * @return 更新后的模型信息
     */
    @PutMapping
    @PreAuthorize("hasRole('SUPERVISOR')")
    public Result<ModelInfo> updateModel(@RequestBody ModelInfo modelInfo) {
        log.info("接收到模型信息更新请求: ID={}, 模型名={}, 版本={}", 
                modelInfo.getModelId(), modelInfo.getModelName(), modelInfo.getVersion());
        
        try {
            ModelInfo updatedModel = modelService.updateModel(modelInfo);
            log.info("模型信息更新成功: ID={}", updatedModel.getModelId());
            return Result.success(updatedModel);
        } catch (Exception e) {
            log.error("模型信息更新异常: {}", e.getMessage(), e);
            return Result.error(500, "模型信息更新失败: " + e.getMessage());
        }
    }

    @PostMapping("/{modelId}/publish")
    @PreAuthorize("hasRole('SUPERVISOR')")
    public Result<ModelInfo> publishModel(@PathVariable Integer modelId) {
        try {
            return Result.success(modelService.publishModel(modelId));
        } catch (Exception e) {
            log.error("模型发布异常: {}", e.getMessage(), e);
            return Result.error(500, "模型发布失败: " + e.getMessage());
        }
    }

    @PostMapping("/{modelId}/set-default")
    @PreAuthorize("hasRole('SUPERVISOR')")
    public Result<ModelInfo> setDefaultModel(@PathVariable Integer modelId) {
        try {
            return Result.success(modelService.setDefaultModel(modelId));
        } catch (Exception e) {
            log.error("设置默认模型异常: {}", e.getMessage(), e);
            return Result.error(500, "设置默认模型失败: " + e.getMessage());
        }
    }

    @PostMapping("/{modelId}/disable")
    @PreAuthorize("hasRole('SUPERVISOR')")
    public Result<ModelInfo> disableModel(@PathVariable Integer modelId) {
        try {
            return Result.success(modelService.disableModel(modelId));
        } catch (Exception e) {
            log.error("停用模型异常: {}", e.getMessage(), e);
            return Result.error(500, "停用模型失败: " + e.getMessage());
        }
    }

    @PostMapping("/{modelId}/archive")
    @PreAuthorize("hasRole('SUPERVISOR')")
    public Result<ModelInfo> archiveModel(@PathVariable Integer modelId) {
        try {
            return Result.success(modelService.archiveModel(modelId));
        } catch (Exception e) {
            log.error("归档模型异常: {}", e.getMessage(), e);
            return Result.error(500, "归档模型失败: " + e.getMessage());
        }
    }

    @PostMapping("/{modelId}/validate")
    @PreAuthorize("hasRole('SUPERVISOR')")
    public Result<ModelInfo> validateModel(@PathVariable Integer modelId) {
        try {
            return Result.success(modelService.validateModel(modelId));
        } catch (Exception e) {
            log.error("模型重新校验异常: {}", e.getMessage(), e);
            return Result.error(500, "模型重新校验失败: " + e.getMessage());
        }
    }

    /**
     * 删除指定 ONNX 模型
     *
     * @param modelId 模型ID
     * @return 删除结果
     */
    @DeleteMapping("/{modelId}")
    @PreAuthorize("hasRole('SUPERVISOR')")
    public Result<Void> deleteModel(@PathVariable("modelId") Integer modelId) {
        log.info("接收到模型删除请求: ID={}", modelId);
        
        try {
            modelService.deleteModel(modelId);
            log.info("模型删除成功: ID={}", modelId);
            return Result.success();
        } catch (Exception e) {
            log.error("模型删除异常: {}", e.getMessage(), e);
            return Result.error(500, "模型删除失败: " + e.getMessage());
        }
    }

    /**
     * 获取所有模型信息
     * @return 模型信息列表
     */
    @GetMapping
    public Result<List<ModelInfo>> getAllModels() {
        log.info("接收到获取所有模型信息请求");
        try {
            List<ModelInfo> models = modelService.getAllModels();
            log.info("成功获取模型列表，数量: {}", models.size());
            if (models.isEmpty()) {
                log.warn("模型列表为空");
            } else {
                log.info("模型列表第一条数据: ID={}, 名称={}, 版本={}", 
                    models.get(0).getModelId(), models.get(0).getModelName(), models.get(0).getVersion());
            }
            return Result.success(models);
        } catch (Exception e) {
            log.error("获取模型列表失败: {}", e.getMessage(), e);
            return Result.error(500, "获取模型列表失败: " + e.getMessage());
        }
    }

    @GetMapping("/{modelId}/operations")
    public Result<List<ModelOperationLog>> getModelOperations(@PathVariable Integer modelId) {
        try {
            return Result.success(modelService.getOperationLogs(modelId));
        } catch (Exception e) {
            log.error("获取模型操作日志失败: {}", e.getMessage(), e);
            return Result.error(500, "获取模型操作日志失败: " + e.getMessage());
        }
    }
} 
