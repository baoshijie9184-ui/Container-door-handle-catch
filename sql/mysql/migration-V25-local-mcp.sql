-- 本地固定 Fetch MCP：每账号状态、安装租约与操作审计。
CREATE TABLE IF NOT EXISTS agent_local_mcp (
  id BIGINT NOT NULL AUTO_INCREMENT, owner_user_id BIGINT NOT NULL, server_key VARCHAR(32) NOT NULL,
  package_version VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'NOT_INSTALLED',
  enabled BOOLEAN NOT NULL DEFAULT FALSE, revision INT NOT NULL DEFAULT 0,
  operation_id VARCHAR(64) NULL, request_id VARCHAR(64) NULL, lease_expires_at DATETIME NULL,
  manifest_json JSON NULL, manifest_sha256 CHAR(64) NULL, error_code VARCHAR(64) NULL,
  created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
  PRIMARY KEY(id), UNIQUE KEY uk_local_mcp_owner(owner_user_id,server_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS agent_local_mcp_audit (
  id BIGINT NOT NULL AUTO_INCREMENT, owner_user_id BIGINT NOT NULL, server_key VARCHAR(32) NOT NULL,
  action_name VARCHAR(32) NOT NULL, outcome VARCHAR(32) NOT NULL, revision INT NOT NULL,
  operation_id VARCHAR(64) NULL, run_id VARCHAR(128) NULL, call_id VARCHAR(160) NULL,
  detail_json JSON NOT NULL, created_at DATETIME NOT NULL,
  PRIMARY KEY(id), KEY idx_local_mcp_audit_owner(owner_user_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
