package com.ruanzhu.doorhandle.module.detection.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 单张图片检测响应DTO
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class SingleImageDetectionResponse {
    /**
     * 检测类别 (Normal-正常, Bent-弯曲, Deformed-形变, Rusty-锈蚀, Missing-缺失, Compromised-结构损伤)
     */
    private String category;
    
    /**
     * 对应类别的置信度 (0-1)
     */
    private Float confidence;
    
    /**
     * 处理后的图像路径（可选）
     */
    private String processedImagePath;
    
    /**
     * 带标注框的图像路径
     */
    private String annotatedImagePath;
    
    /**
     * 错误消息（如果有）
     */
    private String errorMessage;
} 
