package com.ruanzhu.doorhandle.module.model.service;

import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.module.model.entity.ModelOperationLog;
import org.springframework.web.multipart.MultipartFile;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 模型服务接口
 */
public interface ModelService {
    /**
     * 上传模型
     * @param file 模型文件
     * @param modelName 模型名称
     * @param version 版本号
     * @param updateDescription 更新说明
     * @return 模型信息
     */
    ModelInfo uploadModel(MultipartFile file, String modelName, String version, String updateDescription);

    /**
     * 更新 ONNX 模型信息
     * @param modelInfo 模型信息
     * @return 更新后的模型信息
     */
    ModelInfo updateModel(ModelInfo modelInfo);

    /**
     * 删除未被引用的模型登记；物理文件保留待核对回收，数据库回滚不能恢复已删除字节。
     * @param modelId 模型ID
     */
    void deleteModel(Integer modelId);

    /**
     * 发布模型
     */
    ModelInfo publishModel(Integer modelId);

    /**
     * 设置默认模型
     */
    ModelInfo setDefaultModel(Integer modelId);

    /**
     * 停用模型
     */
    ModelInfo disableModel(Integer modelId);

    /**
     * 归档模型
     */
    ModelInfo archiveModel(Integer modelId);

    /**
     * 重新校验模型文件
     */
    ModelInfo validateModel(Integer modelId);

    /**
     * 更新模型使用统计
     */
    void incrementUsageStats(Integer modelId, LocalDateTime usedAt);

    /**
     * 查询模型操作日志
     */
    List<ModelOperationLog> getOperationLogs(Integer modelId);

    /**
     * 获取所有模型信息
     * @return 所有模型信息列表
     */
    List<ModelInfo> getAllModels();
} 
