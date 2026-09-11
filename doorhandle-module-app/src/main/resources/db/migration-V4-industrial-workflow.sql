-- V4: 工业检测闭环骨架
-- 增加批次、工单、业务流转状态和设备在线心跳字段。

ALTER TABLE `detection_task`
    ADD COLUMN IF NOT EXISTS `batch_no` VARCHAR(128) DEFAULT NULL COMMENT '生产/采集批次号' AFTER `task_type`,
    ADD COLUMN IF NOT EXISTS `work_order_no` VARCHAR(128) DEFAULT NULL COMMENT '质检工单号' AFTER `batch_no`,
    ADD COLUMN IF NOT EXISTS `flow_status` VARCHAR(32) DEFAULT NULL COMMENT '业务流转状态' AFTER `work_order_no`;

UPDATE `detection_task`
SET `batch_no` = CONCAT_WS('_', `capture_date`, `region`, `device_name`, `image_folder_name`)
WHERE `batch_no` IS NULL;

UPDATE `detection_task`
SET `work_order_no` = CONCAT('WO-', DATE_FORMAT(COALESCE(`created_at`, NOW()), '%Y%m%d%H%i%s'), '-', `id`)
WHERE `work_order_no` IS NULL;

UPDATE `detection_task`
SET `flow_status` = CASE
    WHEN `status` IN ('COMPLETED', 'PARTIAL_FAILED') THEN 'PENDING_REVIEW'
    WHEN `status` = 'FAILED' THEN 'FAILED'
    WHEN `status` IN ('QUEUED', 'DETECTING', 'UPLOADING_RESULT') THEN 'DETECTING'
    WHEN `status` = 'UPLOADED' THEN 'PENDING_DETECTION'
    ELSE 'UPLOADING'
END
WHERE `flow_status` IS NULL;

CREATE INDEX IF NOT EXISTS `idx_detection_task_batch_no` ON `detection_task` (`batch_no`);
CREATE INDEX IF NOT EXISTS `idx_detection_task_work_order_no` ON `detection_task` (`work_order_no`);
CREATE INDEX IF NOT EXISTS `idx_detection_task_flow_status` ON `detection_task` (`flow_status`);

ALTER TABLE `device_management`
    ADD COLUMN IF NOT EXISTS `online_status` VARCHAR(32) NOT NULL DEFAULT 'OFFLINE' COMMENT '在线状态: ONLINE/OFFLINE' AFTER `status`,
    ADD COLUMN IF NOT EXISTS `last_heartbeat_at` DATETIME DEFAULT NULL COMMENT '最近心跳时间' AFTER `online_status`;

UPDATE `device_management`
SET `online_status` = CASE WHEN `status` = 'OFFLINE' THEN 'OFFLINE' ELSE 'ONLINE' END
WHERE `online_status` IS NULL OR `online_status` = '';
