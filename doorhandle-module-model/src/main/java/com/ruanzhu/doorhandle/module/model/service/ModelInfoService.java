package com.ruanzhu.doorhandle.module.model.service;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;

import java.util.Map;

/**
 * 模型信息服务接口
 */
public interface ModelInfoService {
    
    /**
     * 分页查询模型信息
     *
     * @param page 页码
     * @param size 每页大小
     * @param modelId 模型ID
     * @param modelName 模型名称
     * @param version 版本号
     * @return 分页结果
     */
    Page<ModelInfo> getModelInfoPage(Integer page, Integer size, Integer modelId, String modelName, String version, String status);
    
    /**
     * 根据模型ID获取模型信息
     *
     * @param modelId 模型ID
     * @return 模型信息
     */
    ModelInfo getModelInfoByModelId(Integer modelId);
    
    /**
     * 保存模型信息
     *
     * @param modelInfo 模型信息
     * @return 是否成功
     */
    boolean saveModelInfo(ModelInfo modelInfo);
    
    /**
     * 更新模型信息
     *
     * @param modelInfo 模型信息
     * @return 是否成功
     */
    boolean updateModelInfo(ModelInfo modelInfo);

    /**
     * 记录模型评估指标
     *
     * @param modelId 模型ID
     * @param evaluation 评估指标
     * @return 是否成功
     */
    boolean recordEvaluation(Integer modelId, ModelInfo evaluation);

    /**
     * 配置模型发布/灰度/A-B/回滚策略
     *
     * @param modelId 模型ID
     * @param deploymentStrategy 部署策略
     * @param canaryPercent 灰度比例
     * @param abGroup A/B 分组
     * @param rollbackFromModelId 回滚来源模型
     * @return 是否成功
     */
    boolean configureRollout(Integer modelId, String deploymentStrategy, Integer canaryPercent,
                             String abGroup, Integer rollbackFromModelId);
    
    /**
     * 删除模型信息
     *
     * @param modelId 模型ID
     * @return 是否成功
     */
    boolean deleteModelInfoByModelId(Integer modelId);
} 
