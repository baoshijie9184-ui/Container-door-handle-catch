-- 固定 Fetch 安装持久队列。先执行 V25；不自动重放已经开始的安装。
CREATE TABLE IF NOT EXISTS agent_mcp_install_job (
  id BIGINT NOT NULL AUTO_INCREMENT,
  operation_id VARCHAR(64) NOT NULL,
  owner_user_id BIGINT NOT NULL,
  owner_username VARCHAR(128) NOT NULL,
  runtime_sha256 CHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'QUEUED',
  worker_token VARCHAR(64) NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  PRIMARY KEY(id),
  UNIQUE KEY uk_mcp_install_operation(operation_id),
  KEY idx_mcp_install_pending(status,id),
  KEY idx_mcp_install_owner(owner_user_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
