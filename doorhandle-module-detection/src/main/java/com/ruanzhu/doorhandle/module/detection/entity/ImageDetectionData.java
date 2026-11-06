package com.ruanzhu.doorhandle.module.detection.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 图像检测数据实体类（已废弃）
 *
 * @deprecated 新检测使用 {@link DetectionTask}；此类型保留历史聚合 CRUD 的兼容契约。
 * 历史聚合独立存入 historical_detection_summary，不转换为当前检测任务。
 */
@Data
@TableName("historical_detection_summary")
@Deprecated
public class ImageDetectionData {

    /** 主键ID */
    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    /** 图片文件夹的路径 */
    @TableField("folder_path")
    private String folderPath;

    /** 检测结果路径（.txt 或 .json） */
    @TableField("result_path")
    private String resultPath;

    /** 带标注框的图片文件夹路径 */
    @TableField("annotated_images_path")
    private String annotatedImagesPath;

    /** 检测图片数量 */
    @TableField("detected_images_count")
    private Integer detectedImagesCount;

    /** 检测结果实例数量 */
    @TableField("detection_instances_count")
    private Integer detectionInstancesCount;

    /** 正常数量 */
    @TableField("normal_count")
    private Integer normalCount;

    /** 弯曲数量 */
    @TableField("bent_count")
    private Integer bentCount;

    /** 形变数量 */
    @TableField("deformed_count")
    private Integer deformedCount;

    /** 锈蚀数量 */
    @TableField("rusty_count")
    private Integer rustyCount;

    /** 缺失数量 */
    @TableField("missing_count")
    private Integer missingCount;

    /** 结构损伤数量 */
    @TableField("compromised_count")
    private Integer compromisedCount;

    /** 图片漏检率（百分比） */
    @TableField("miss_detection_rate")
    private Double missDetectionRate;

    /** 检测开始时间 */
    @TableField("start_time")
    private LocalDateTime startTime;

    /** 检测完成时间 */
    @TableField("finished_at")
    private LocalDateTime finishedAt;

    /** 使用的模型ID */
    @TableField("model_id")
    private Integer modelId;
}
