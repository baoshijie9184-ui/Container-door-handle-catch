CREATE TABLE IF NOT EXISTS `operation_audit_log` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `operator` VARCHAR(64) NOT NULL,
    `action` VARCHAR(32) NOT NULL,
    `resource_type` VARCHAR(64) NOT NULL,
    `resource_id` VARCHAR(128) DEFAULT NULL,
    `request_method` VARCHAR(16) DEFAULT NULL,
    `request_path` VARCHAR(512) DEFAULT NULL,
    `change_summary` JSON DEFAULT NULL,
    `result` VARCHAR(16) NOT NULL,
    `client_ip` VARCHAR(45) DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_audit_operator_time` (`operator`, `created_at`),
    KEY `idx_audit_resource_time` (`resource_type`, `resource_id`, `created_at`),
    KEY `idx_audit_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
