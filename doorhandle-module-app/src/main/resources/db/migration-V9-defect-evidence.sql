USE doorhandledb;

ALTER TABLE `detection_task`
    ADD COLUMN `defect_evidence_json` LONGTEXT DEFAULT NULL COMMENT '结构化缺陷证据 JSON，包含缺陷框/面积/置信度/位置/严重等级' AFTER `statistics_json`,
    ADD COLUMN `defect_count` INT NOT NULL DEFAULT 0 COMMENT '结构化缺陷数量' AFTER `defect_evidence_json`,
    ADD COLUMN `primary_defect_type` VARCHAR(64) DEFAULT NULL COMMENT '主要缺陷类型' AFTER `defect_count`,
    ADD COLUMN `max_defect_severity` VARCHAR(32) DEFAULT NULL COMMENT '最高缺陷严重等级: MINOR/MAJOR/CRITICAL' AFTER `primary_defect_type`;

ALTER TABLE `detection_task`
    ADD KEY `idx_detection_task_primary_defect` (`primary_defect_type`, `created_at` DESC),
    ADD KEY `idx_detection_task_severity_created` (`max_defect_severity`, `created_at` DESC),
    ADD KEY `idx_detection_task_device_defect` (`device_name`, `primary_defect_type`, `created_at` DESC);
