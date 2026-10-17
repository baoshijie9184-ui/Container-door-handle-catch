-- Requires V31. Export receipts contain hashes and counts, never URLs, excerpts or answers.
CREATE TABLE IF NOT EXISTS agent_research_export_audit (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  export_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
  user_id BIGINT NOT NULL,
  run_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
  format_version INT NOT NULL,
  source_count INT NOT NULL,
  expired_source_count INT NOT NULL,
  payload_bytes INT NOT NULL,
  payload_sha256 CHAR(64) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_research_export (export_id),
  KEY idx_research_export_owner (user_id,run_id,id),
  CONSTRAINT fk_research_export_run FOREIGN KEY (run_id) REFERENCES agent_run(run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
