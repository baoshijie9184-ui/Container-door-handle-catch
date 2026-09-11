-- ============================================================
-- 模型生命周期与操作日志迁移脚本 V3
-- 幂等迁移：支持已有字段/索引/表的环境重复执行。
-- ============================================================

DELIMITER //

DROP PROCEDURE IF EXISTS add_column_if_missing//
CREATE PROCEDURE add_column_if_missing(IN p_table VARCHAR(64), IN p_column VARCHAR(64), IN p_definition TEXT)
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_table AND COLUMN_NAME = p_column
  ) THEN
    SET @ddl = CONCAT('ALTER TABLE `', p_table, '` ADD COLUMN ', p_definition);
    PREPARE stmt FROM @ddl;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END//

DROP PROCEDURE IF EXISTS add_index_if_missing//
CREATE PROCEDURE add_index_if_missing(IN p_table VARCHAR(64), IN p_index VARCHAR(64), IN p_definition TEXT)
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_table AND INDEX_NAME = p_index
  ) THEN
    SET @ddl = CONCAT('ALTER TABLE `', p_table, '` ADD ', p_definition);
    PREPARE stmt FROM @ddl;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END//

DELIMITER ;

-- model_management 补充生命周期字段
CALL add_column_if_missing('model_management', 'status', '`status` VARCHAR(32) NOT NULL DEFAULT ''READY'' COMMENT ''模型状态: DRAFT/READY/PUBLISHED/DISABLED/ARCHIVED'' AFTER `update_description`');
CALL add_column_if_missing('model_management', 'is_default', '`is_default` TINYINT(1) NOT NULL DEFAULT 0 COMMENT ''是否默认模型'' AFTER `status`');
CALL add_column_if_missing('model_management', 'creator', '`creator` VARCHAR(64) DEFAULT NULL COMMENT ''上传人'' AFTER `is_default`');
CALL add_column_if_missing('model_management', 'published_at', '`published_at` DATETIME DEFAULT NULL COMMENT ''发布时间'' AFTER `creator`');
CALL add_column_if_missing('model_management', 'last_used_at', '`last_used_at` DATETIME DEFAULT NULL COMMENT ''最近使用时间'' AFTER `published_at`');
CALL add_column_if_missing('model_management', 'usage_count', '`usage_count` INT NOT NULL DEFAULT 0 COMMENT ''使用次数'' AFTER `last_used_at`');
CALL add_column_if_missing('model_management', 'validation_status', '`validation_status` VARCHAR(32) NOT NULL DEFAULT ''PENDING'' COMMENT ''校验状态: PENDING/PASSED/FAILED'' AFTER `usage_count`');
CALL add_column_if_missing('model_management', 'validation_message', '`validation_message` VARCHAR(255) DEFAULT NULL COMMENT ''校验说明'' AFTER `validation_status`');

-- 历史数据回填
UPDATE `model_management`
SET `status` = CASE
        WHEN `status` IS NULL OR `status` = '' THEN 'READY'
        ELSE `status`
    END,
    `creator` = COALESCE(NULLIF(`creator`, ''), 'system'),
    `validation_status` = CASE
        WHEN `validation_status` IS NULL OR `validation_status` = '' THEN 'PASSED'
        ELSE `validation_status`
    END,
    `validation_message` = COALESCE(NULLIF(`validation_message`, ''), '历史数据默认通过基础校验');

-- 回填使用统计
UPDATE `model_management` m
LEFT JOIN (
    SELECT `model_id`,
           COUNT(*) AS task_count,
           MAX(COALESCE(`finished_at`, `started_at`, `created_at`)) AS last_used_at
    FROM `detection_task`
    WHERE `model_id` IS NOT NULL
    GROUP BY `model_id`
) t ON t.`model_id` = m.`model_id`
SET m.`usage_count` = COALESCE(t.`task_count`, m.`usage_count`, 0),
    m.`last_used_at` = COALESCE(t.`last_used_at`, m.`last_used_at`);

-- 没有默认模型时，自动选一个已发布/最近上传的模型作为默认
SET @default_count = (SELECT COUNT(*) FROM `model_management` WHERE `is_default` = 1);
SET @default_model_id = (
    SELECT `model_id`
    FROM `model_management`
    ORDER BY CASE WHEN `status` = 'PUBLISHED' THEN 0 ELSE 1 END, `upload_time` DESC
    LIMIT 1
);
UPDATE `model_management`
SET `is_default` = CASE
        WHEN @default_count = 0 AND `model_id` = @default_model_id THEN 1
        ELSE `is_default`
    END,
    `status` = CASE
        WHEN @default_count = 0 AND `model_id` = @default_model_id AND `status` = 'READY' THEN 'PUBLISHED'
        ELSE `status`
    END,
    `published_at` = CASE
        WHEN @default_count = 0 AND `model_id` = @default_model_id AND `published_at` IS NULL THEN `upload_time`
        ELSE `published_at`
    END;

CALL add_index_if_missing('model_management', 'idx_model_status', 'INDEX `idx_model_status` (`status`)');
CALL add_index_if_missing('model_management', 'idx_model_is_default', 'INDEX `idx_model_is_default` (`is_default`)');
CALL add_index_if_missing('model_management', 'idx_model_last_used_at', 'INDEX `idx_model_last_used_at` (`last_used_at`)');

-- 模型操作日志表
CREATE TABLE IF NOT EXISTS `model_operation_log` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `model_id` INT NOT NULL COMMENT '模型ID',
    `operation_type` VARCHAR(32) NOT NULL COMMENT '操作类型',
    `operator` VARCHAR(64) DEFAULT NULL COMMENT '操作人',
    `operation_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '操作时间',
    `remark` VARCHAR(255) DEFAULT NULL COMMENT '备注',
    PRIMARY KEY (`id`),
    KEY `idx_model_operation_log_model_id` (`model_id`),
    KEY `idx_model_operation_log_time` (`operation_time`),
    CONSTRAINT `fk_model_operation_log_model`
        FOREIGN KEY (`model_id`) REFERENCES `model_management` (`model_id`)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='模型操作日志表';

-- 为历史模型补一条初始化日志（避免空日志）
INSERT INTO `model_operation_log` (`model_id`, `operation_type`, `operator`, `operation_time`, `remark`)
SELECT m.`model_id`, 'INIT', COALESCE(m.`creator`, 'system'), COALESCE(m.`upload_time`, NOW()), '历史模型初始化为生命周期管理'
FROM `model_management` m
WHERE NOT EXISTS (
    SELECT 1
    FROM `model_operation_log` l
    WHERE l.`model_id` = m.`model_id`
);

DROP PROCEDURE IF EXISTS add_column_if_missing;
DROP PROCEDURE IF EXISTS add_index_if_missing;
