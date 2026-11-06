-- Historical seven-table source only. Never an application startup schema.
CREATE TABLE detection_creation_owner (
 user_id BIGINT PRIMARY KEY
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE detection_creation_job (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 command_id VARCHAR(36) NOT NULL,
 actor_user_id BIGINT NOT NULL,
 actor_username VARCHAR(50) NOT NULL,
 actor_role VARCHAR(24) NOT NULL,
 request_id VARCHAR(128) NOT NULL,
 proposal_id VARCHAR(128) NOT NULL,
 task_id VARCHAR(128) NOT NULL,
 dispatch_id VARCHAR(64) NOT NULL,
 session_id VARCHAR(128) NOT NULL,
 preview_json MEDIUMTEXT NOT NULL,
 preview_sha256 CHAR(64) NOT NULL,
 status VARCHAR(24) NOT NULL,
 owner_token VARCHAR(36) NULL,
 lease_until DATETIME(6) NULL,
 reason_code VARCHAR(64) NULL,
 created_at DATETIME(6) NOT NULL,
 updated_at DATETIME(6) NOT NULL,
 revision BIGINT NOT NULL DEFAULT 0,
 bucket_name VARCHAR(128) NULL,
 source_prefix VARCHAR(512) COLLATE utf8mb4_bin NULL,
 manifest_sha256 CHAR(64) COLLATE utf8mb4_bin NULL,
 UNIQUE KEY uk_detection_creation_command(command_id),
 UNIQUE KEY uk_detection_creation_request(actor_user_id,request_id),
 UNIQUE KEY uk_detection_creation_task(task_id),
 KEY idx_detection_creation_ready(status,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE detection_creation_object (
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

CREATE TABLE detection_creation_review (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 check_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
 command_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
 actor_user_id BIGINT NOT NULL,
 request_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
 expected_revision BIGINT NOT NULL,
 action VARCHAR(24) NOT NULL,
 source_check_id VARCHAR(36) COLLATE utf8mb4_bin NULL,
 status VARCHAR(24) NOT NULL,
 worker_token VARCHAR(36) COLLATE utf8mb4_bin NULL,
 lease_until DATETIME(6) NULL,
 checked_count INT NOT NULL DEFAULT 0,
 verified_count INT NOT NULL DEFAULT 0,
 evidence_json MEDIUMTEXT NULL,
 evidence_sha256 CHAR(64) COLLATE utf8mb4_bin NULL,
 completed_revision BIGINT NULL,
 reason_code VARCHAR(64) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_creation_review_id(check_id),
 UNIQUE KEY uk_creation_review_request(actor_user_id,request_id),
 KEY idx_creation_review_queue(status,id),
 KEY idx_creation_review_command(command_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE detection_execution_command (
 command_id VARCHAR(128) PRIMARY KEY,
 actor_user_id BIGINT NOT NULL,
 request_id VARCHAR(128) NOT NULL,
 command_type VARCHAR(24) NOT NULL,
 payload_sha256 CHAR(64) NOT NULL,
 proposal_id VARCHAR(128) NULL,
 task_id VARCHAR(128) NOT NULL,
 dispatch_id VARCHAR(64) NOT NULL,
 result_json JSON NOT NULL,
 created_at DATETIME(6) NOT NULL,
 UNIQUE KEY uk_detection_command_request(actor_user_id,request_id),
 KEY idx_detection_command_task(task_id,dispatch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE detection_dispatch_outbox (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 event_id VARCHAR(128) NOT NULL,
 task_id VARCHAR(128) NOT NULL,
 dispatch_id VARCHAR(64) NOT NULL,
 payload_json MEDIUMTEXT NOT NULL,
 payload_sha256 CHAR(64) NOT NULL,
 actor_user_id BIGINT NOT NULL,
 request_id VARCHAR(128) NOT NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'PENDING',
 attempts INT NOT NULL DEFAULT 0,
 lease_token VARCHAR(64) NULL,
 lease_until DATETIME(6) NULL,
 next_attempt_at DATETIME(6) NOT NULL,
 last_error_code VARCHAR(48) NULL,
 created_at DATETIME(6) NOT NULL,
 updated_at DATETIME(6) NOT NULL,
 UNIQUE KEY uk_detection_outbox_event(event_id),
 UNIQUE KEY uk_detection_outbox_dispatch(task_id,dispatch_id),
 KEY idx_detection_outbox_ready(status,next_attempt_at,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE detection_worker_receipt (
 task_id VARCHAR(128) NOT NULL,
 dispatch_id VARCHAR(64) NOT NULL,
 event_id VARCHAR(128) NOT NULL,
 payload_sha256 CHAR(64) NOT NULL,
 owner_id VARCHAR(64) NOT NULL,
 status VARCHAR(24) NOT NULL,
 result_json MEDIUMTEXT NULL,
 result_sha256 CHAR(64) NULL,
 started_at DATETIME(6) NOT NULL,
 updated_at DATETIME(6) NOT NULL,
 PRIMARY KEY(task_id,dispatch_id),
 UNIQUE KEY uk_detection_worker_event(event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
