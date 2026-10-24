-- AI-owned exit evidence. Application rollback preserves receipts and unresolved reservations.
CREATE TABLE IF NOT EXISTS agent_mcp_execution (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 execution_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
 owner_user_id BIGINT NOT NULL,
 installation_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
 runtime_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 pool_id CHAR(32) COLLATE utf8mb4_bin NOT NULL,
 purpose VARCHAR(16) NOT NULL,
 state VARCHAR(24) NOT NULL,
 revision INT NOT NULL DEFAULT 0,
 exit_verified BOOLEAN NOT NULL DEFAULT FALSE,
 cleanup_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
 run_id VARCHAR(128) NULL,
 call_id VARCHAR(160) NULL,
 lease_expires_at DATETIME(6) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_mcp_execution(execution_id),
 KEY idx_mcp_execution_owner(owner_user_id,state,id),
 KEY idx_mcp_execution_installation(owner_user_id,installation_id,state),
 KEY idx_mcp_execution_expiry(state,lease_expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_mcp_execution_command (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 owner_user_id BIGINT NOT NULL,
 request_id VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
 execution_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
 request_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 status VARCHAR(24) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_mcp_execution_request(owner_user_id,request_id),
 KEY idx_mcp_execution_command(owner_user_id,execution_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
