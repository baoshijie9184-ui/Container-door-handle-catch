-- Detection-owned immutable targets and one-attempt upload receipts. Preserve on application rollback.
ALTER TABLE detection_creation_job
 ADD COLUMN revision BIGINT NOT NULL DEFAULT 0,
 ADD COLUMN bucket_name VARCHAR(128) NULL,
 ADD COLUMN source_prefix VARCHAR(512) COLLATE utf8mb4_bin NULL,
 ADD COLUMN manifest_sha256 CHAR(64) COLLATE utf8mb4_bin NULL;
CREATE TABLE IF NOT EXISTS detection_creation_object (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 command_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
 image_index INT NOT NULL,
 file_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
 object_key VARCHAR(1024) COLLATE utf8mb4_bin NOT NULL,
 content_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 byte_length BIGINT NOT NULL,
 content_type VARCHAR(64) NOT NULL,
 state VARCHAR(24) NOT NULL DEFAULT 'PLANNED',
 upload_token VARCHAR(36) COLLATE utf8mb4_bin NULL,
 etag VARCHAR(128) NULL,
 object_version VARCHAR(1024) NULL,
 oss_request_id VARCHAR(128) NULL,
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_detection_creation_object(command_id,image_index),
 UNIQUE KEY uk_detection_creation_file(command_id,file_id),
 KEY idx_creation_object_state(command_id,state,image_index)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
