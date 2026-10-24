-- Preserve process evidence and transport labels during application rollback.
ALTER TABLE agent_mcp_execution ADD COLUMN transport VARCHAR(32) NOT NULL DEFAULT 'STREAMABLE_HTTP';
ALTER TABLE agent_fetch_installation
 ADD COLUMN reconcile_request VARCHAR(64) COLLATE utf8mb4_bin NULL,
 ADD COLUMN reconcile_expires_at DATETIME(6) NULL,
 ADD COLUMN writer_evidence_code VARCHAR(48) NULL;
CREATE TABLE IF NOT EXISTS agent_mcp_install_worker (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 owner_user_id BIGINT NOT NULL,
 installation_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
 node_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 runtime_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 controller_pid BIGINT NOT NULL,
 controller_started VARCHAR(48) NOT NULL,
 container_id CHAR(64) COLLATE utf8mb4_bin NULL,
 container_started VARCHAR(64) NULL,
 controller_pool_id CHAR(32) COLLATE utf8mb4_bin NULL,
 state VARCHAR(24) NOT NULL,
 revision INT NOT NULL DEFAULT 0,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_mcp_install_worker(owner_user_id,installation_id),
 KEY idx_mcp_install_worker_state(owner_user_id,state,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
