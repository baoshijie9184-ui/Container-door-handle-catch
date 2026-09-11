package com.ruanzhu.doorhandle.module.detection.dto;

import lombok.Data;
import org.springframework.web.multipart.MultipartFile;

/**
 * 图像检测请求DTO
 */
@Data
public class ImageDetectionRequest {
    /**
     * 上传的图像文件
     */
    private MultipartFile imageFile;
    
    /**
     * 所使用的模型ID（可选）
     */
    private Integer modelId;
    
    /**
     * 标签数据输出格式（YOLO 或 COCO）
     */
    private String outputFormat;
    
    /**
     * 置信度阈值
     */
    private Float confidenceThreshold;
} 