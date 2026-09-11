-- V5: 检测结果专业化 - 人工复核与误报反馈

ALTER TABLE `detection_task`
    ADD COLUMN IF NOT EXISTS `review_status` VARCHAR(32) DEFAULT NULL COMMENT '复核状态: PENDING/REVIEWED' AFTER `error_message`,
    ADD COLUMN IF NOT EXISTS `review_conclusion` VARCHAR(64) DEFAULT NULL COMMENT '复核结论' AFTER `review_status`,
    ADD COLUMN IF NOT EXISTS `severity_level` VARCHAR(32) DEFAULT NULL COMMENT '严重等级' AFTER `review_conclusion`,
    ADD COLUMN IF NOT EXISTS `confirmed_defect_count` INT DEFAULT 0 COMMENT '人工确认缺陷数' AFTER `severity_level`,
    ADD COLUMN IF NOT EXISTS `false_positive_count` INT DEFAULT 0 COMMENT '误报数量' AFTER `confirmed_defect_count`,
    ADD COLUMN IF NOT EXISTS `review_remark` VARCHAR(1000) DEFAULT NULL COMMENT '复核备注' AFTER `false_positive_count`,
    ADD COLUMN IF NOT EXISTS `reviewer` VARCHAR(64) DEFAULT NULL COMMENT '复核人' AFTER `review_remark`,
    ADD COLUMN IF NOT EXISTS `reviewed_at` DATETIME DEFAULT NULL COMMENT '复核时间' AFTER `reviewer`;

UPDATE `detection_task`
SET `review_status` = CASE
    WHEN `flow_status` = 'CONFIRMED' THEN 'REVIEWED'
    WHEN `status` IN ('COMPLETED', 'PARTIAL_FAILED') THEN 'PENDING'
    ELSE NULL
END
WHERE `review_status` IS NULL;

CREATE INDEX IF NOT EXISTS `idx_detection_task_review_status` ON `detection_task` (`review_status`);
CREATE INDEX IF NOT EXISTS `idx_detection_task_severity_level` ON `detection_task` (`severity_level`);
