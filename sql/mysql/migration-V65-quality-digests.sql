-- UTC DATETIME storage; schedule expressions and report calendar use Asia/Shanghai.
CREATE TABLE IF NOT EXISTS quality_digest_control(control_id INT NOT NULL PRIMARY KEY,CHECK(control_id=1)) ENGINE=InnoDB;
INSERT IGNORE INTO quality_digest_control(control_id) VALUES(1);
CREATE TABLE IF NOT EXISTS quality_digest_schedule (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, schedule_id VARCHAR(64) NOT NULL, owner_user_id BIGINT NOT NULL,
 owner_username VARCHAR(100) NOT NULL, name VARCHAR(120) NOT NULL, cron_expression VARCHAR(100) NOT NULL,
 enabled BOOLEAN NOT NULL, version INT NOT NULL, next_fire_at DATETIME(6) NULL,
 created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
 UNIQUE KEY uk_digest_schedule(schedule_id), KEY idx_digest_due(enabled,next_fire_at,id),
 KEY idx_digest_owner(owner_user_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS quality_digest_run (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, run_id VARCHAR(64) NOT NULL, schedule_id VARCHAR(64) NOT NULL,
 owner_user_id BIGINT NOT NULL, request_key VARCHAR(100) NOT NULL, scheduled_for DATETIME(6) NOT NULL,
 report_date DATE NOT NULL, status VARCHAR(16) NOT NULL, claim_token VARCHAR(64) NULL, lease_until DATETIME(6) NULL,
 snapshot_json JSON NULL, snapshot_sha256 CHAR(64) NULL, error_code VARCHAR(64) NULL,
 created_at DATETIME(6) NOT NULL, finished_at DATETIME(6) NULL,
 UNIQUE KEY uk_digest_run(run_id), UNIQUE KEY uk_digest_slot(schedule_id,request_key),
 KEY idx_digest_claim(status,lease_until,id), KEY idx_digest_run_owner(owner_user_id,id),
 CONSTRAINT fk_digest_run_schedule FOREIGN KEY(schedule_id) REFERENCES quality_digest_schedule(schedule_id),
 CHECK(status IN ('PENDING','RUNNING','COMPLETED','FAILED','BLOCKED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS quality_digest_audit (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, schedule_id VARCHAR(64) NOT NULL, actor_user_id BIGINT NOT NULL,
 action_name VARCHAR(24) NOT NULL, version INT NOT NULL, detail_json JSON NOT NULL, created_at DATETIME(6) NOT NULL,
 KEY idx_digest_audit(schedule_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS quality_digest_command (
 actor_user_id BIGINT NOT NULL, request_id VARCHAR(64) NOT NULL, request_sha256 CHAR(64) NOT NULL,
 schedule_id VARCHAR(64) NOT NULL, created_at DATETIME(6) NOT NULL, PRIMARY KEY(actor_user_id,request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
