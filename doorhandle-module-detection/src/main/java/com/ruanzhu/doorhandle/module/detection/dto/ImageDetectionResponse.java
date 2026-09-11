package com.ruanzhu.doorhandle.module.detection.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 图像检测响应DTO
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ImageDetectionResponse {
    /**
     * 检测任务ID
     */
    private Long id;
    
    /**
     * 检测任务状态（SUCCESS/FAILED/PROCESSING）
     */
    private String status;
    
    /**
     * 检测结果路径（.txt 或 .json）
     */
    private String resultPath;
    
    /**
     * 检测图片数量
     */
    private Integer detectedImagesCount;
    
    /**
     * 检测结果实例数量
     */
    private Integer detectionInstancesCount;
    
    /**
     * 正常数量
     */
    private Integer normalCount;

    /**
     * 弯曲数量
     */
    private Integer bentCount;

    /**
     * 形变数量
     */
    private Integer deformedCount;

    /**
     * 锈蚀数量
     */
    private Integer rustyCount;

    /**
     * 缺失数量
     */
    private Integer missingCount;

    /**
     * 结构损伤数量
     */
    private Integer compromisedCount;
    
    /**
     * 图片漏检率（百分比）
     */
    private Double missDetectionRate;
    
    /**
     * 使用的模型ID
     */
    private Integer modelId;
    
    /**
     * 错误消息（如果有）
     */
    private String errorMessage;
} 
