-- AI-owned shared image retirement fences. Keep all fences, commands and receipts on rollback.
CREATE TABLE IF NOT EXISTS agent_fetch_image (
 image_id VARCHAR(80) COLLATE utf8mb4_bin NOT NULL PRIMARY KEY,
 state VARCHAR(24) NOT NULL DEFAULT 'ACTIVE',
 revision INT NOT NULL DEFAULT 0,
 cleanup_request VARCHAR(36) COLLATE utf8mb4_bin NULL,
 cleanup_owner_user_id BIGINT NULL,
 runner_pool_id CHAR(32) COLLATE utf8mb4_bin NULL,
 archive_sha256 CHAR(64) COLLATE utf8mb4_bin NULL,
 image_absent BOOLEAN NOT NULL DEFAULT FALSE,
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_fetch_image_command (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 owner_user_id BIGINT NOT NULL,
 request_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
 image_id VARCHAR(80) COLLATE utf8mb4_bin NOT NULL,
 request_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 action_name VARCHAR(16) NOT NULL,
 state VARCHAR(24) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_fetch_image_request(owner_user_id,request_id),
 KEY idx_fetch_image_command(image_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
ALTER TABLE agent_mcp_execution ADD COLUMN image_id VARCHAR(80) COLLATE utf8mb4_bin NULL;
