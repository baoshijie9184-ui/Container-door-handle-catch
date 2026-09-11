package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.detection.dto.ImageDetectionResponse;
import com.ruanzhu.doorhandle.module.detection.dto.SingleImageDetectionResponse;
import com.ruanzhu.doorhandle.module.detection.service.ImageDetectionService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

/**
 * 单个图像检测控制器
 */
@RestController
@RequestMapping("/api/image-detection")
@RequiredArgsConstructor
@Slf4j
@Tag(name = "单个图像检测", description = "单个图像检测相关接口")
public class SingleImageDetectionController {

    private final ImageDetectionService imageDetectionService;

    /**
     * 上传单个图像进行检测
     * @param imageFile 图像文件
     * @param modelId 可选的模型ID
     * @return 检测结果
     */
    @PostMapping(value = "/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    @Operation(summary = "上传图像并进行检测", description = "上传单张图像进行门把手状态检测")
    public Result<SingleImageDetectionResponse> uploadImageForDetection(
            @RequestParam("imageFile") MultipartFile imageFile,
            @RequestParam(value = "modelId", required = false) Integer modelId
    ) {
        log.info("接收到图像上传检测请求，文件名：{}，文件大小：{}，模型ID：{}", 
                imageFile.getOriginalFilename(), imageFile.getSize(), modelId);
        
        try {
            // 验证图像文件
            if (imageFile == null || imageFile.isEmpty()) {
                log.error("上传的图像文件为空");
                return Result.error("请上传有效的图像文件");
            }
            
            // 调用服务处理检测
            log.info("开始处理图像检测，模型ID：{}", modelId);
            SingleImageDetectionResponse response = imageDetectionService.detectImage(imageFile, modelId);
            
            if (response.getErrorMessage() != null) {
                log.error("图像检测失败: {}", response.getErrorMessage());
                return Result.error(response.getErrorMessage());
            }
            
            // 确保返回的图像路径是正确的URL格式
            if (response.getAnnotatedImagePath() != null && !response.getAnnotatedImagePath().startsWith("/")) {
                response.setAnnotatedImagePath("/" + response.getAnnotatedImagePath());
                log.info("调整后的标注图像路径: {}", response.getAnnotatedImagePath());
            }
            
            if (response.getProcessedImagePath() != null && !response.getProcessedImagePath().startsWith("/")) {
                response.setProcessedImagePath("/" + response.getProcessedImagePath());
                log.info("调整后的处理图像路径: {}", response.getProcessedImagePath());
            }
            
            log.info("图像检测完成，类别：{}，置信度：{}", response.getCategory(), response.getConfidence());
            return Result.success(response);
        } catch (Exception e) {
            log.error("图像检测处理异常", e);
            return Result.error("图像检测失败: " + e.getMessage());
        }
    }
    
    /**
     * 上传多个图像进行批量检测
     * @param files 图像文件列表
     * @param modelId 可选的模型ID
     * @param outputFormat 输出格式（YOLO/COCO）
     * @param confidenceThreshold 置信度阈值
     * @return 批量检测任务信息
     */
    @PostMapping(value = "/batch", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    @Operation(summary = "批量上传图像并进行检测", description = "上传多张图像进行门把手状态批量检测")
    public Result<ImageDetectionResponse> batchUploadImagesForDetection(
            @RequestParam("files") List<MultipartFile> files,
            @RequestParam(value = "modelId", required = false) Integer modelId,
            @RequestParam(value = "outputFormat", defaultValue = "COCO") String outputFormat,
            @RequestParam(value = "confidenceThreshold", defaultValue = "0.5") Float confidenceThreshold
    ) {
        log.info("接收到批量图像上传检测请求，文件数量：{}，模型ID：{}，输出格式：{}，置信度阈值：{}", 
                files.size(), modelId, outputFormat, confidenceThreshold);
        
        try {
            // 验证图像文件
            if (files == null || files.isEmpty()) {
                log.error("上传的图像文件列表为空");
                return Result.error("请上传至少一个有效的图像文件");
            }
            
            // 检查文件内容
            for (int i = 0; i < files.size(); i++) {
                MultipartFile file = files.get(i);
                if (file.isEmpty()) {
                    log.error("文件 {} 为空", i+1);
                    return Result.error("上传的文件不能为空");
                }
                log.info("文件 {}: 名称={}, 大小={}, 内容类型={}", 
                        i+1, file.getOriginalFilename(), file.getSize(), file.getContentType());
            }
            
            // 调用服务处理批量检测
            log.info("开始处理批量图像检测，文件数量：{}", files.size());
            ImageDetectionResponse response = imageDetectionService.processImageDetection(
                    files, modelId, outputFormat, confidenceThreshold);
            
            // 确保路径格式正确
            if (response.getResultPath() != null && !response.getResultPath().startsWith("/")) {
                response.setResultPath("/" + response.getResultPath());
                log.info("调整后的结果路径: {}", response.getResultPath());
            }
            
            log.info("批量图像检测任务已创建：{}", response);
            return Result.success(response);
        } catch (Exception e) {
            log.error("批量图像检测处理异常", e);
            return Result.error("批量图像检测失败: " + e.getMessage());
        }
    }
} 