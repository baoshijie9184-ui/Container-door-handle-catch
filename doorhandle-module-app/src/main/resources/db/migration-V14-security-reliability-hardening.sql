-- V14: authorization and asynchronous-processing idempotency fields.
-- Each DDL statement is guarded for databases that may already contain part of the migration.

SET @schema_name = DATABASE();

SET @ddl = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'users' AND COLUMN_NAME = 'role') = 0,
    'ALTER TABLE `users` ADD COLUMN `role` VARCHAR(16) NOT NULL DEFAULT ''OPERATOR'' AFTER `phone`',
    'SELECT 1'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

UPDATE `users`
SET `role` = CASE WHEN LOWER(username) = 'admin' THEN 'ADMIN' ELSE 'OPERATOR' END
WHERE `role` IS NULL OR `role` NOT IN ('ADMIN', 'OPERATOR') OR LOWER(username) = 'admin';

SET @ddl = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'detection_task' AND COLUMN_NAME = 'dispatch_id') = 0,
    'ALTER TABLE `detection_task` ADD COLUMN `dispatch_id` VARCHAR(64) NULL AFTER `stage`',
    'SELECT 1'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'detection_task' AND COLUMN_NAME = 'last_finished_event_id') = 0,
    'ALTER TABLE `detection_task` ADD COLUMN `last_finished_event_id` VARCHAR(128) NULL AFTER `dispatch_id`',
    'SELECT 1'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'chat_pending_action' AND COLUMN_NAME = 'error_message') = 0,
    'ALTER TABLE `chat_pending_action` ADD COLUMN `error_message` VARCHAR(500) NULL AFTER `confirmed_at`',
    'SELECT 1'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF(
    (SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'detection_task' AND INDEX_NAME = 'idx_detection_dispatch_id') = 0,
    'CREATE INDEX `idx_detection_dispatch_id` ON `detection_task` (`dispatch_id`)',
    'SELECT 1'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
