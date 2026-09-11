-- V8: 质检处置闭环
-- 在人工复核后记录放行、返工、复检、隔离、报废等工业现场处置动作。

ALTER TABLE `detection_task`
    ADD COLUMN IF NOT EXISTS `disposition_status` VARCHAR(32) DEFAULT NULL COMMENT '处置状态: PENDING/DISPOSED' AFTER `reviewed_at`,
    ADD COLUMN IF NOT EXISTS `disposition_action` VARCHAR(32) DEFAULT NULL COMMENT '处置动作: RELEASE/REWORK/RECHECK/HOLD/SCRAP' AFTER `disposition_status`,
    ADD COLUMN IF NOT EXISTS `disposition_remark` VARCHAR(1000) DEFAULT NULL COMMENT '处置备注' AFTER `disposition_action`,
    ADD COLUMN IF NOT EXISTS `disposition_operator` VARCHAR(64) DEFAULT NULL COMMENT '处置人' AFTER `disposition_remark`,
    ADD COLUMN IF NOT EXISTS `disposed_at` DATETIME DEFAULT NULL COMMENT '处置时间' AFTER `disposition_operator`,
    ADD COLUMN IF NOT EXISTS `recheck_required` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否需要复检' AFTER `disposed_at`;

UPDATE `detection_task`
SET `disposition_status` = CASE
    WHEN `flow_status` IN ('RELEASED', 'REWORK_REQUIRED', 'RECHECK_REQUIRED', 'HOLD', 'SCRAPPED') THEN 'DISPOSED'
    WHEN `review_status` = 'REVIEWED' THEN 'PENDING'
    ELSE NULL
END
WHERE `disposition_status` IS NULL;

CREATE INDEX IF NOT EXISTS `idx_detection_task_disposition_status` ON `detection_task` (`disposition_status`);
CREATE INDEX IF NOT EXISTS `idx_detection_task_disposed_at` ON `detection_task` (`disposed_at`);
CREATE INDEX IF NOT EXISTS `idx_detection_task_disposition_action` ON `detection_task` (`disposition_action`);
