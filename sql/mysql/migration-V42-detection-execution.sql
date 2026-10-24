-- V42: additive command receipts, transaction outbox and worker execution fences.
CREATE TABLE IF NOT EXISTS detection_execution_command (
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
CREATE TABLE IF NOT EXISTS detection_dispatch_outbox (
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
CREATE TABLE IF NOT EXISTS detection_worker_receipt (
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
