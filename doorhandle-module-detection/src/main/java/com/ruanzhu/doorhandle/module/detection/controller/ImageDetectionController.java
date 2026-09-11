package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.detection.dto.ImageDetectionResponse;
import com.ruanzhu.doorhandle.module.detection.dto.SingleImageDetectionResponse;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.service.ImageDetectionService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

/**
 * 图像检测控制器
 */
@RestController
@RequestMapping("/api/detection")
@RequiredArgsConstructor
@Slf4j
@Tag(name = "图像检测", description = "图像检测相关接口")
public class ImageDetectionController {

    private final ImageDetectionService imageDetectionService;

    /**
     * 上传图片进行检测
     *
     * @param files 图片文件列表
     * @param modelId 模型ID
     * @param outputFormat 输出格式（YOLO/COCO）
     * @param confidenceThreshold 置信度阈值
     * @return 检测结果
     */
    @PostMapping("/upload")
    public Result<ImageDetectionResponse> uploadImages(
            @RequestParam("files") List<MultipartFile> files,
            @RequestParam("modelId") Integer modelId,
            @RequestParam("outputFormat") String outputFormat,
            @RequestParam(value = "confidenceThreshold", defaultValue = "0.5") Float confidenceThreshold) {
        
        log.info("接收到图像检测请求: 模型ID={}, 输出格式={}, 置信度阈值={}", 
                modelId, outputFormat, confidenceThreshold);
        
        // 检查是否上传了文件
        if (files == null) {
            log.error("文件列表为null");
            return Result.error(400, "请选择至少一张图片");
        }
        
        log.info("接收到的文件数量: {}", files.size());
        
        if (files.isEmpty()) {
            log.error("文件列表为空");
            return Result.error(400, "请选择至少一张图片");
        }
        
        // 检查文件内容
        for (int i = 0; i < files.size(); i++) {
            MultipartFile file = files.get(i);
            log.info("文件 {}: 名称={}, 大小={}, 内容类型={}", 
                    i+1, file.getOriginalFilename(), file.getSize(), file.getContentType());
            
            if (file.isEmpty()) {
                log.error("文件 {} 为空", i+1);
                return Result.error(400, "上传的文件不能为空");
            }
        }
        
        try {
            log.info("开始处理图像检测请求");
            ImageDetectionResponse response = imageDetectionService.processImageDetection(
                    files, modelId, outputFormat, confidenceThreshold);
            
            log.info("图像检测请求处理成功: {}", response);
            return Result.success(response);
        } catch (Exception e) {
            log.error("图像检测处理异常: {}", e.getMessage(), e);
            return Result.error(500, "图像检测失败: " + e.getMessage());
        }
    }

    /**
     * 获取所有检测记录
     *
     * @return 检测记录列表
     */
    @GetMapping
    public Result<List<DetectionTask>> getAllDetectionData() {
        log.info("接收到获取所有检测记录请求");
        try {
            List<DetectionTask> dataList = imageDetectionService.getAllDetectionData();
            log.info("成功获取到 {} 条检测记录", dataList.size());
            return Result.success(dataList);
        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            log.error("获取检测记录异常: {}", e.getMessage(), e);
            return Result.error(500, "获取检测记录失败: " + e.getMessage());
        }
    }

    /**
     * 获取检测记录详情
     *
     * @param id 检测记录ID
     * @return 检测记录详情
     */
    @GetMapping("/{id}")
    public Result<DetectionTask> getDetectionDataById(@PathVariable("id") Long id) {
        log.info("接收到获取检测记录详情请求: ID={}", id);
        try {
            DetectionTask data = imageDetectionService.getDetectionDataById(id);
            if (data == null) {
                log.warn("检测记录不存在: ID={}", id);
                return Result.error(404, "检测记录不存在");
            }
            log.info("成功获取检测记录详情: ID={}", id);
            return Result.success(data);
        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            log.error("获取检测记录详情异常: {}", e.getMessage(), e);
            return Result.error(500, "获取检测记录详情失败: " + e.getMessage());
        }
    }

    /**
     * 删除检测记录
     *
     * @param id 检测记录ID
     * @return 操作结果
     */
    @DeleteMapping("/{id}")
    public Result<Void> deleteDetectionData(@PathVariable("id") Long id) {
        log.info("接收到删除检测记录请求: ID={}", id);
        try {
            imageDetectionService.deleteDetectionData(id);
            log.info("成功删除检测记录: ID={}", id);
            return Result.success();
        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            log.error("删除检测记录异常: {}", e.getMessage(), e);
            return Result.error(500, "删除检测记录失败: " + e.getMessage());
        }
    }

    /**
     * 上传多张图片并进行检测
     * @param files 图片文件列表
     * @param modelId 模型ID
     * @param outputFormat 输出格式
     * @param confidenceThreshold 置信度阈值
     * @return 检测结果
     */
    @PostMapping("/upload-and-detect")
    public Result<ImageDetectionResponse> uploadAndDetect(
            @RequestParam("files") List<MultipartFile> files,
            @RequestParam("modelId") Integer modelId,
            @RequestParam(defaultValue = "YOLO") String outputFormat,
            @RequestParam(defaultValue = "0.5") Float confidenceThreshold
    ) {
        log.info("接收到批量图片上传检测请求，文件数量：{}，模型ID：{}，格式：{}，阈值：{}", 
                files.size(), modelId, outputFormat, confidenceThreshold);
        
        if (files.isEmpty()) {
            return Result.error("请至少上传一张图片");
        }
        
        try {
            ImageDetectionResponse response = imageDetectionService.processImageDetection(
                    files, modelId, outputFormat, confidenceThreshold);
            return Result.success(response);
        } catch (BusinessException e) {
            log.error("业务处理异常", e);
            return Result.error(e.getMessage());
        } catch (Exception e) {
            log.error("系统异常", e);
            return Result.error("系统错误：" + e.getMessage());
        }
    }

}
