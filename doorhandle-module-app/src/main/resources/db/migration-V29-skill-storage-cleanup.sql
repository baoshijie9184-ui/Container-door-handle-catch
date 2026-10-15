-- Cleanup commands retain their audit even after unreferenced download files are removed.
CREATE TABLE IF NOT EXISTS agent_skill_storage_command (
  id BIGINT NOT NULL AUTO_INCREMENT,
  owner_user_id BIGINT NOT NULL,
  request_id VARCHAR(64) NOT NULL,
  request_sha256 CHAR(64) NOT NULL,
  download_id VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL,
  removed_bytes BIGINT NOT NULL DEFAULT 0,
  removed_files INT NOT NULL DEFAULT 0,
  error_code VARCHAR(80) NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  PRIMARY KEY(id),
  UNIQUE KEY uk_skill_storage_request(owner_user_id,request_id),
  KEY idx_skill_storage_owner(owner_user_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
