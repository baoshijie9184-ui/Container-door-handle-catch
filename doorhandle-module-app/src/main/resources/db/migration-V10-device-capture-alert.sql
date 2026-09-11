-- V10: 采集端运行状态与异常告警
-- 幂等迁移：支持已有字段/索引/表的环境重复执行。

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

CALL add_column_if_missing('device_management', 'station_code', '`station_code` VARCHAR(64) DEFAULT NULL COMMENT ''产线工位编号'' AFTER `last_heartbeat_at`');
CALL add_column_if_missing('device_management', 'edge_node_id', '`edge_node_id` VARCHAR(64) DEFAULT NULL COMMENT ''边缘工控节点编号'' AFTER `station_code`');
CALL add_column_if_missing('device_management', 'plc_status', '`plc_status` VARCHAR(32) DEFAULT NULL COMMENT ''PLC状态'' AFTER `edge_node_id`');
CALL add_column_if_missing('device_management', 'camera_status', '`camera_status` VARCHAR(32) DEFAULT NULL COMMENT ''相机状态'' AFTER `plc_status`');
CALL add_column_if_missing('device_management', 'capture_status', '`capture_status` VARCHAR(32) DEFAULT NULL COMMENT ''采集状态'' AFTER `camera_status`');
CALL add_column_if_missing('device_management', 'last_image_key', '`last_image_key` VARCHAR(255) DEFAULT NULL COMMENT ''最近采集图片OSS Key'' AFTER `capture_status`');
CALL add_column_if_missing('device_management', 'last_capture_at', '`last_capture_at` DATETIME DEFAULT NULL COMMENT ''最近采集时间'' AFTER `last_image_key`');
CALL add_column_if_missing('device_management', 'runtime_metadata_json', '`runtime_metadata_json` LONGTEXT DEFAULT NULL COMMENT ''设备运行态扩展元数据JSON'' AFTER `last_capture_at`');

CALL add_index_if_missing('device_management', 'idx_device_station_online', 'INDEX `idx_device_station_online` (`station_code`, `online_status`, `last_heartbeat_at` DESC)');
CALL add_index_if_missing('device_management', 'idx_device_edge_node', 'INDEX `idx_device_edge_node` (`edge_node_id`)');

CREATE TABLE IF NOT EXISTS `device_capture_alert` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `alert_id` VARCHAR(64) NOT NULL COMMENT '告警编号',
    `device_id` BIGINT DEFAULT NULL COMMENT '设备ID',
    `device_code` VARCHAR(50) NOT NULL COMMENT '设备编号快照',
    `device_type` VARCHAR(50) DEFAULT NULL COMMENT '设备类型快照',
    `station_code` VARCHAR(64) DEFAULT NULL COMMENT '产线工位编号',
    `edge_node_id` VARCHAR(64) DEFAULT NULL COMMENT '边缘工控节点编号',
    `alert_type` VARCHAR(64) NOT NULL COMMENT '告警类型: CAPTURE_EXCEPTION/HEARTBEAT_OFFLINE',
    `alert_level` VARCHAR(32) NOT NULL DEFAULT 'MAJOR' COMMENT '告警等级: MINOR/MAJOR/CRITICAL',
    `alert_message` VARCHAR(500) NOT NULL COMMENT '告警说明',
    `runtime_snapshot_json` LONGTEXT DEFAULT NULL COMMENT '告警发生时运行态快照JSON',
    `status` VARCHAR(32) NOT NULL DEFAULT 'OPEN' COMMENT '状态: OPEN/ACKNOWLEDGED/RESOLVED',
    `ack_operator` VARCHAR(64) DEFAULT NULL COMMENT '确认人',
    `ack_remark` VARCHAR(500) DEFAULT NULL COMMENT '确认备注',
    `acknowledged_at` DATETIME DEFAULT NULL COMMENT '确认时间',
    `resolved_operator` VARCHAR(64) DEFAULT NULL COMMENT '关闭人',
    `resolved_remark` VARCHAR(500) DEFAULT NULL COMMENT '关闭备注',
    `resolved_at` DATETIME DEFAULT NULL COMMENT '关闭时间',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_device_capture_alert_id` (`alert_id`),
    KEY `idx_capture_alert_status_created` (`status`, `created_at` DESC),
    KEY `idx_capture_alert_device_created` (`device_code`, `created_at` DESC),
    KEY `idx_capture_alert_level_created` (`alert_level`, `created_at` DESC),
    KEY `idx_capture_alert_station_status` (`station_code`, `status`, `created_at` DESC),
    CONSTRAINT `fk_capture_alert_device` FOREIGN KEY (`device_id`) REFERENCES `device_management` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='采集端异常告警表';

DROP PROCEDURE IF EXISTS add_column_if_missing;
DROP PROCEDURE IF EXISTS add_index_if_missing;
