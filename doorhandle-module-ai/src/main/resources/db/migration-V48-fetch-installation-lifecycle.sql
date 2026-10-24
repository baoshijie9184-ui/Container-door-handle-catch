-- AI-owned fixed Fetch snapshots and explicit storage commands. Keep these tables on rollback.
CREATE TABLE IF NOT EXISTS agent_fetch_installation (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 owner_user_id BIGINT NOT NULL,
 installation_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
 prior_installation_id VARCHAR(36) COLLATE utf8mb4_bin NULL,
 state VARCHAR(24) NOT NULL,
 revision INT NOT NULL DEFAULT 0,
 writer_exit_verified BOOLEAN NOT NULL DEFAULT FALSE,
 retained_for_rollback BOOLEAN NOT NULL DEFAULT FALSE,
 package_version VARCHAR(64) NOT NULL,
 transport VARCHAR(32) NOT NULL,
 image_id VARCHAR(80) NULL,
 manifest_json JSON NULL,
 manifest_sha256 CHAR(64) COLLATE utf8mb4_bin NULL,
 cleanup_request VARCHAR(64) COLLATE utf8mb4_bin NULL,
 cleanup_expires_at DATETIME(6) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_fetch_installation(owner_user_id,installation_id),
 KEY idx_fetch_installation_state(owner_user_id,state,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_fetch_lifecycle_command (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 owner_user_id BIGINT NOT NULL,
 request_id VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
 installation_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
 action_name VARCHAR(24) NOT NULL,
 request_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 status VARCHAR(24) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_fetch_lifecycle_request(owner_user_id,request_id),
 KEY idx_fetch_lifecycle_install(owner_user_id,installation_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
