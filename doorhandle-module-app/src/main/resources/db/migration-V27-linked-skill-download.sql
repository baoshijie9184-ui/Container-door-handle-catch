-- Public linked Skill downloads are private until explicitly submitted for review.
CREATE TABLE IF NOT EXISTS agent_skill_download (
  id BIGINT NOT NULL AUTO_INCREMENT,
  download_id VARCHAR(64) NOT NULL,
  owner_user_id BIGINT NOT NULL,
  request_id VARCHAR(64) NOT NULL,
  request_sha256 CHAR(64) NOT NULL,
  source_url VARCHAR(1000) NOT NULL,
  target_role VARCHAR(32) NOT NULL,
  status VARCHAR(32) NOT NULL,
  manifest_json JSON NULL,
  manifest_sha256 CHAR(64) NULL,
  skill_id VARCHAR(64) NULL,
  error_code VARCHAR(80) NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  PRIMARY KEY(id),
  UNIQUE KEY uk_skill_download(download_id),
  UNIQUE KEY uk_skill_download_request(owner_user_id,request_id),
  KEY idx_skill_download_owner(owner_user_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
