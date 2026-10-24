-- Model module owns these records. No file is removed by this migration or by restart.
CREATE TABLE IF NOT EXISTS detection_model_file_journal (
 file_id CHAR(36) COLLATE utf8mb4_bin NOT NULL PRIMARY KEY,
 actor_user_id BIGINT NOT NULL,
 request_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
 storage_path VARCHAR(2048) COLLATE utf8mb4_bin NOT NULL,
 path_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 content_sha256 CHAR(64) COLLATE utf8mb4_bin NULL,
 byte_size BIGINT NULL,
 model_id INT NULL,
 state VARCHAR(32) NOT NULL,
 revision BIGINT NOT NULL DEFAULT 0,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_detection_model_file_path(path_sha256),
 UNIQUE KEY uk_detection_model_upload_request(actor_user_id,request_id),
 KEY idx_detection_model_file_model(model_id,state),
 KEY idx_detection_model_file_pending(state,updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS detection_model_file_retention (
 retention_id CHAR(36) COLLATE utf8mb4_bin NOT NULL PRIMARY KEY,
 model_id INT NOT NULL,
 actor_user_id BIGINT NOT NULL,
 request_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
 file_id CHAR(36) COLLATE utf8mb4_bin NULL,
 storage_path VARCHAR(2048) COLLATE utf8mb4_bin NOT NULL,
 path_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 content_sha256 CHAR(64) COLLATE utf8mb4_bin NULL,
 byte_size BIGINT NULL,
 state VARCHAR(32) NOT NULL,
 revision BIGINT NOT NULL DEFAULT 0,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 KEY idx_detection_model_retention_model(model_id),
 KEY idx_detection_model_retention_state(state,updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
