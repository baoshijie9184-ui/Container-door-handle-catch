package com.ruanzhu.doorhandle.module.model.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import com.fasterxml.jackson.databind.annotation.JsonDeserialize;
import com.ruanzhu.doorhandle.module.model.util.ModelImageCountDeserializer;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDateTime;

/**
 * 检测模型登记资料（兼容 PTH 与 ONNX）
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

    /** 训练集原始图片数量，不按增强次数累计。 */
    @TableField("training_image_count")
    @JsonDeserialize(using = ModelImageCountDeserializer.class)
    private Integer trainingImageCount;

    /** 实际训练完成日期时间，按业务时区 UTC+8 登记。 */
    @TableField("training_completed_at")
    private LocalDateTime trainingCompletedAt;

    /** 本次评估成功完成检测的图片数，不含执行失败图片。 */
    @TableField("evaluation_image_count")
    @JsonDeserialize(using = ModelImageCountDeserializer.class)
    private Integer evaluationImageCount;

    /** 本次评估中一个目标也未检出的图片数，Normal 检出也算检出。 */
    @TableField("no_detection_image_count")
    @JsonDeserialize(using = ModelImageCountDeserializer.class)
    private Integer noDetectionImageCount;

    /** 指定环境和批大小下实测的每秒处理图片数量，不从延迟取倒数。 */
    @TableField("inference_fps")
    private BigDecimal inferenceFps;

    /** 派生统计，不保存另一份比例，也不读取历史 missDetectionRate。 */
    @com.fasterxml.jackson.annotation.JsonProperty(access = com.fasterxml.jackson.annotation.JsonProperty.Access.READ_ONLY)
    public BigDecimal getNoDetectionRate() {
        if (evaluationImageCount == null || evaluationImageCount <= 0 || noDetectionImageCount == null
                || noDetectionImageCount < 0 || noDetectionImageCount > evaluationImageCount) return null;
        return BigDecimal.valueOf(noDetectionImageCount)
                .divide(BigDecimal.valueOf(evaluationImageCount), 8, RoundingMode.HALF_UP);
    }

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
