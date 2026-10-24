-- AI-owned durable quota coordination. No existing download is assumed to have exited after a restart.
CREATE TABLE IF NOT EXISTS agent_skill_download_owner (
 owner_user_id BIGINT NOT NULL PRIMARY KEY
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_skill_download_event (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 owner_user_id BIGINT NOT NULL,
 download_id VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
 action VARCHAR(40) NOT NULL,
 status VARCHAR(24) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 KEY idx_skill_download_event(owner_user_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_skill_download_lease (
 download_id VARCHAR(64) COLLATE utf8mb4_bin NOT NULL PRIMARY KEY,
 owner_user_id BIGINT NOT NULL,
 status VARCHAR(24) NOT NULL,
 reserved_bytes BIGINT NOT NULL DEFAULT 5242880,
 worker_instance VARCHAR(36) COLLATE utf8mb4_bin NULL,
 process_pid BIGINT NULL,
 process_started_at VARCHAR(40) NULL,
 exit_verified BOOLEAN NOT NULL DEFAULT FALSE,
 lease_expires_at DATETIME(6) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 KEY idx_skill_lease_owner(owner_user_id,status),
 KEY idx_skill_lease_expiry(status,lease_expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
