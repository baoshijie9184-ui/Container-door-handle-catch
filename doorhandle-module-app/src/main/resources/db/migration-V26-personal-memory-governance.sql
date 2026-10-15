-- 本人长期记忆设置与治理审计；不迁移、不删除已有 Mem0 记忆。
CREATE TABLE IF NOT EXISTS agent_memory_preference (
  owner_user_id BIGINT NOT NULL, read_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  save_enabled BOOLEAN NOT NULL DEFAULT TRUE, revision INT NOT NULL DEFAULT 0,
  updated_at DATETIME NOT NULL,
  PRIMARY KEY(owner_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS agent_memory_audit (
  id BIGINT NOT NULL AUTO_INCREMENT, owner_user_id BIGINT NOT NULL,
  action_name VARCHAR(32) NOT NULL, outcome VARCHAR(32) NOT NULL,
  request_key VARCHAR(64) NULL, memory_id VARCHAR(64) NULL, content_digest CHAR(64) NULL,
  preference_revision INT NULL, read_enabled BOOLEAN NULL, save_enabled BOOLEAN NULL,
  created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
  PRIMARY KEY(id), UNIQUE KEY uk_memory_request(owner_user_id,request_key),
  KEY idx_memory_audit_owner(owner_user_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
