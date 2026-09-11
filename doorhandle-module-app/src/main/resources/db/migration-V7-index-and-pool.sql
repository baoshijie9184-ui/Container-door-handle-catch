-- V7: MySQL performance indexes for high-frequency dashboard, task, chat and device queries.
-- Safe to re-run: each index is created only when absent.

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'model_management' AND INDEX_NAME = 'idx_model_management_status_upload'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_model_management_status_upload ON model_management (status, upload_time DESC)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'model_management' AND INDEX_NAME = 'idx_model_management_default_status'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_model_management_default_status ON model_management (is_default, status)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'model_management' AND INDEX_NAME = 'idx_model_management_validation_status'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_model_management_validation_status ON model_management (validation_status)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'model_operation_log' AND INDEX_NAME = 'idx_model_operation_log_model_time'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_model_operation_log_model_time ON model_operation_log (model_id, operation_time DESC, id DESC)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'detection_task' AND INDEX_NAME = 'idx_detection_task_status_created'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_detection_task_status_created ON detection_task (status, created_at DESC)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'detection_task' AND INDEX_NAME = 'idx_detection_task_collector_created'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_detection_task_collector_created ON detection_task (collector, created_at DESC)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'detection_task' AND INDEX_NAME = 'idx_detection_task_device_created'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_detection_task_device_created ON detection_task (device_name, created_at DESC)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'detection_task' AND INDEX_NAME = 'idx_detection_task_region_created'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_detection_task_region_created ON detection_task (region, created_at DESC)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'detection_task' AND INDEX_NAME = 'idx_detection_task_review_time'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_detection_task_review_time ON detection_task (review_status, reviewed_at DESC)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'detection_task' AND INDEX_NAME = 'idx_detection_task_flow_created'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_detection_task_flow_created ON detection_task (flow_status, created_at DESC)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'detection_task' AND INDEX_NAME = 'idx_detection_task_creator_created'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_detection_task_creator_created ON detection_task (created_by, created_at DESC)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'chat_session' AND INDEX_NAME = 'idx_chat_session_user_status_updated'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_chat_session_user_status_updated ON chat_session (username, status, updated_at DESC)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'chat_session' AND INDEX_NAME = 'idx_chat_session_user_status_pinned_updated'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_chat_session_user_status_pinned_updated ON chat_session (username, status, pinned DESC, updated_at DESC)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'chat_pending_action' AND INDEX_NAME = 'idx_chat_pending_session_status_created'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_chat_pending_session_status_created ON chat_pending_action (session_id, status, created_at DESC)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'employee' AND INDEX_NAME = 'idx_employee_status'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_employee_status ON employee (status)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'employee' AND INDEX_NAME = 'idx_employee_type_status'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_employee_type_status ON employee (employee_type, status)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'device_management' AND INDEX_NAME = 'idx_device_type_status'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_device_type_status ON device_management (device_type, status)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'device_management' AND INDEX_NAME = 'idx_device_online_heartbeat'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_device_online_heartbeat ON device_management (online_status, last_heartbeat_at DESC)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'device_usage_record' AND INDEX_NAME = 'idx_usage_device_start'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_usage_device_start ON device_usage_record (device_id, start_time DESC)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'device_usage_record' AND INDEX_NAME = 'idx_usage_employee_start'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_usage_employee_start ON device_usage_record (employee_id, start_time DESC)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'device_usage_record' AND INDEX_NAME = 'idx_usage_status_start'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_usage_status_start ON device_usage_record (status, start_time DESC)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
    SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'device_usage_record' AND INDEX_NAME = 'idx_usage_active_device'
);
SET @sql = IF(@idx_exists = 0, 'CREATE INDEX idx_usage_active_device ON device_usage_record (device_id, status, end_time, start_time DESC)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
