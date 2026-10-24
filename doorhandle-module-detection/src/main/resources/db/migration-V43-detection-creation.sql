-- Approved image transfers are fenced before network I/O. Unknown transfers are never replayed on restart.
CREATE TABLE IF NOT EXISTS detection_creation_owner (
 user_id BIGINT PRIMARY KEY
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS detection_creation_job (
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
 UNIQUE KEY uk_detection_creation_command(command_id),
 UNIQUE KEY uk_detection_creation_request(actor_user_id,request_id),
 UNIQUE KEY uk_detection_creation_task(task_id),
 KEY idx_detection_creation_ready(status,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
