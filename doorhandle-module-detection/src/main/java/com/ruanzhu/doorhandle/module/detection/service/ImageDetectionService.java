package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.module.detection.dto.ImageDetectionResponse;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.dto.SingleImageDetectionResponse;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

/**
 * 图像检测服务接口
 */
public interface ImageDetectionService {
    
    /**
     * 处理图像检测请求
     * @param files 上传的图片文件
     * @param modelId 模型ID
     * @param outputFormat 输出格式（YOLO/COCO）
     * @param confidenceThreshold 置信度阈值
     * @return 检测响应
     */
    ImageDetectionResponse processImageDetection(
            List<MultipartFile> files,
            Integer modelId,
            String outputFormat,
            Float confidenceThreshold
    );
    
    /**
     * 获取所有图像检测数据
     * @return 图像检测数据列表
     */
    List<DetectionTask> getAllDetectionData();

    /**
     * 根据ID获取图像检测数据
     * @param id 检测数据ID
     * @return 图像检测数据
     */
    DetectionTask getDetectionDataById(Long id);
    
    /**
     * 删除图像检测数据
     * @param id 检测数据ID
     */
    void deleteDetectionData(Long id);

    /**
     * 上传并检测单个图像
     * @param imageFile 上传的图像文件
     * @param modelId 可选的模型ID，如果不提供则使用默认模型
     * @return 图像检测结果
     */
    SingleImageDetectionResponse detectImage(MultipartFile imageFile, Integer modelId);
} 