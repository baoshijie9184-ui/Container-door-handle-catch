package com.ruanzhu.doorhandle.module.model.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * ONNX模型信息实体类
 */
@Data
@TableName("model_management")
public class ModelInfo {
    
    /**
     * 模型唯一标识ID（主键）
     */
    @TableId(value = "model_id", type = IdType.INPUT)
    private Integer modelId;
    
    /**
     * 模型名称
     */
    @TableField("model_name")
    private String modelName;
    
    /**
     * 版本号
     */
    @TableField("version")
    private String version;
    
    /**
     * 模型文件路径
     */
    @TableField("model_path")
    private String modelPath;
    
    /**
     * 上传时间
     */
    @TableField("upload_time")
    private LocalDateTime uploadTime;
    
    /**
     * 更新说明
     */
    @TableField("update_description")
    private String updateDescription;

    /**
     * 生命周期状态
     */
    @TableField("status")
    private String status;

    /**
     * 是否默认模型
     */
    @TableField("is_default")
    private Boolean isDefault;

    /**
     * 上传人
     */
    @TableField("creator")
    private String creator;

    /**
     * 发布时间
     */
    @TableField("published_at")
    private LocalDateTime publishedAt;

    /**
     * 最近使用时间
     */
    @TableField("last_used_at")
    private LocalDateTime lastUsedAt;

    /**
     * 使用次数
     */
    @TableField("usage_count")
    private Integer usageCount;

    /**
     * 校验状态
     */
    @TableField("validation_status")
    private String validationStatus;

    /**
     * 校验说明
     */
    @TableField("validation_message")
    private String validationMessage;

    /**
     * MLOps 状态
     */
    @TableField("mlops_status")
    private String mlopsStatus;

    /**
     * 评估测试集名称
     */
    @TableField("evaluation_dataset")
    private String evaluationDataset;

    /**
     * 精确率
     */
    @TableField("precision_score")
    private BigDecimal precisionScore;

    /**
     * 召回率
     */
    @TableField("recall_score")
    private BigDecimal recallScore;

    /**
     * mAP 指标
     */
    @TableField("map_score")
    private BigDecimal mapScore;

    /**
     * F1 指标
     */
    @TableField("f1_score")
    private BigDecimal f1Score;

    /**
     * 平均推理耗时（毫秒）
     */
    @TableField("avg_inference_ms")
    private Integer avgInferenceMs;

    /**
     * 兼容性说明
     */
    @TableField("compatibility_note")
    private String compatibilityNote;

    /**
     * 部署策略: FULL/CANARY/AB_TEST/ROLLBACK
     */
    @TableField("deployment_strategy")
    private String deploymentStrategy;

    /**
     * 灰度流量比例
     */
    @TableField("canary_percent")
    private Integer canaryPercent;

    /**
     * A/B 测试分组
     */
    @TableField("ab_group")
    private String abGroup;

    /**
     * 回滚来源模型ID
     */
    @TableField("rollback_from_model_id")
    private Integer rollbackFromModelId;
} 
