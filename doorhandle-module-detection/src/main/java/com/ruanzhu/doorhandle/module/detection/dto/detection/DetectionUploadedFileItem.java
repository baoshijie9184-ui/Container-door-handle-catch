package com.ruanzhu.doorhandle.module.detection.dto.detection;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class DetectionUploadedFileItem {
    @NotBlank(message = "文件名不能为空")
    private String fileName;
    @NotBlank(message = "对象 key 不能为空")
    private String objectKey;
    private String etag;

    /** 图片内容 SHA-256，用于批量预检查去重；前端本地计算后提交。 */
    private String sha256;
}
