-- 受控技能演化：本人授权来源、不可变版本、服务端 Eval、发布审计。
CREATE TABLE IF NOT EXISTS agent_skill_source (
  id BIGINT NOT NULL AUTO_INCREMENT, user_id BIGINT NOT NULL, run_id VARCHAR(128) NOT NULL,
  evidence_json JSON NOT NULL, evidence_sha256 CHAR(64) NOT NULL, captured_at DATETIME NOT NULL,
  PRIMARY KEY(id), UNIQUE KEY uk_skill_source(user_id,run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS agent_learned_skill (
  id BIGINT NOT NULL AUTO_INCREMENT, skill_id VARCHAR(64) NOT NULL, owner_user_id BIGINT NOT NULL,
  name VARCHAR(64) NOT NULL, target_role VARCHAR(16) NOT NULL, latest_version INT NOT NULL,
  active_version INT NULL, revision INT NOT NULL, lifecycle VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
  use_count BIGINT NOT NULL DEFAULT 0, last_used_at DATETIME NULL, activated_at DATETIME NULL,
  created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
  PRIMARY KEY(id), UNIQUE KEY uk_learned_skill_id(skill_id), KEY idx_skill_owner(owner_user_id,id),
  KEY idx_skill_active(target_role,lifecycle,active_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS agent_skill_version (
  id BIGINT NOT NULL AUTO_INCREMENT, skill_id VARCHAR(64) NOT NULL, version_no INT NOT NULL,
  owner_user_id BIGINT NOT NULL, request_id VARCHAR(64) NOT NULL, request_sha256 CHAR(64) NOT NULL,
  description_text VARCHAR(300) NOT NULL, instructions_text TEXT NOT NULL, tool_names_json JSON NOT NULL,
  source_run_id VARCHAR(128) NOT NULL, evidence_json JSON NOT NULL, content_sha256 CHAR(64) NOT NULL,
  status VARCHAR(16) NOT NULL, reviewer_user_id BIGINT NULL, review_reason VARCHAR(500) NULL,
  created_at DATETIME NOT NULL, submitted_at DATETIME NULL, reviewed_at DATETIME NULL,
  PRIMARY KEY(id), UNIQUE KEY uk_skill_version(skill_id,version_no), UNIQUE KEY uk_skill_request(owner_user_id,request_id),
  KEY idx_skill_review(status,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS agent_skill_eval (
  id BIGINT NOT NULL AUTO_INCREMENT, skill_id VARCHAR(64) NOT NULL, version_no INT NOT NULL,
  content_sha256 CHAR(64) NOT NULL, suite_version VARCHAR(64) NOT NULL, passed BOOLEAN NOT NULL,
  result_json JSON NOT NULL, actor_user_id BIGINT NOT NULL, created_at DATETIME NOT NULL,
  PRIMARY KEY(id), KEY idx_skill_eval(skill_id,version_no,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS agent_skill_audit (
  id BIGINT NOT NULL AUTO_INCREMENT, skill_id VARCHAR(64) NOT NULL, version_no INT NOT NULL,
  actor_user_id BIGINT NOT NULL, action_name VARCHAR(32) NOT NULL, revision INT NOT NULL,
  content_sha256 CHAR(64) NOT NULL, reason VARCHAR(500) NULL,
  run_id VARCHAR(128) NULL, call_id VARCHAR(160) NULL, created_at DATETIME NOT NULL,
  PRIMARY KEY(id), KEY idx_skill_audit(skill_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
