package com.ruanzhu.doorhandle.module.detection.dto.detection;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class DetectionReviewRequest {

    @Pattern(regexp = "^(PASS|DEFECT|RECHECK|REJECT|CONFIRMED_DEFECT|FALSE_POSITIVE|NORMAL_RELEASE|NEEDS_RECHECK)$",
            message = "复核结论必须是 PASS、DEFECT、RECHECK、REJECT、CONFIRMED_DEFECT、FALSE_POSITIVE、NORMAL_RELEASE 或 NEEDS_RECHECK")
    private String reviewConclusion;

    @Pattern(regexp = "^(LOW|MEDIUM|HIGH|CRITICAL|MINOR|MAJOR)$",
            message = "严重等级必须是 LOW、MEDIUM、HIGH、CRITICAL、MINOR 或 MAJOR")
    private String severityLevel;

    @Min(value = 0, message = "确认缺陷数不能为负数")
    private Integer confirmedDefectCount;

    @Min(value = 0, message = "误报数不能为负数")
    private Integer falsePositiveCount;

    @Size(max = 500, message = "复核备注不能超过 500 个字符")
    private String reviewRemark;
}
