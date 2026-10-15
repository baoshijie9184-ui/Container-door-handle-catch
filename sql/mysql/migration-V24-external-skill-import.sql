-- V23 之后执行；外部包是独立来源，不能冒充成功运行。
CREATE TABLE IF NOT EXISTS agent_skill_import (
  id BIGINT NOT NULL AUTO_INCREMENT, import_id VARCHAR(64) NOT NULL, owner_user_id BIGINT NOT NULL,
  request_id VARCHAR(64) NOT NULL, request_sha256 CHAR(64) NOT NULL,
  payload_json JSON NOT NULL, payload_sha256 CHAR(64) NOT NULL, created_at DATETIME NOT NULL,
  PRIMARY KEY(id), UNIQUE KEY uk_skill_import(import_id), UNIQUE KEY uk_skill_import_request(owner_user_id,request_id),
  KEY idx_skill_import_owner(owner_user_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
-- 以下列变更只执行一次；本地迁移入口通过 information_schema 检查后执行。
ALTER TABLE agent_skill_version MODIFY source_run_id VARCHAR(128) NULL;
ALTER TABLE agent_skill_version ADD COLUMN source_type VARCHAR(32) NOT NULL DEFAULT 'RUN';
ALTER TABLE agent_skill_version ADD COLUMN source_import_id VARCHAR(64) NULL;
