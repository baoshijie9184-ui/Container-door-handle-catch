-- Requires V16. Additive tables only. Does not modify existing messages or run events.
CREATE TABLE IF NOT EXISTS agent_research_source (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  source_id VARCHAR(40) COLLATE utf8mb4_bin NOT NULL,
  user_id BIGINT NOT NULL,
  run_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
  call_id VARCHAR(160) COLLATE utf8mb4_bin NOT NULL,
  requested_url VARCHAR(2048) NOT NULL,
  query_omitted BOOLEAN NOT NULL,
  url_redacted BOOLEAN NOT NULL,
  title VARCHAR(160) NOT NULL,
  excerpt VARCHAR(1000) NOT NULL,
  content_sha256 CHAR(64) NOT NULL,
  request_sha256 CHAR(64) NOT NULL,
  text_chars INT NOT NULL,
  start_index INT NOT NULL,
  max_length INT NOT NULL,
  fetched_at DATETIME(6) NOT NULL,
  expires_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_research_source (source_id),
  UNIQUE KEY uk_research_call (user_id,run_id,call_id),
  KEY idx_research_owner_run (user_id,run_id,id),
  KEY idx_research_expiry (expires_at,id),
  CONSTRAINT fk_research_source_run FOREIGN KEY (run_id) REFERENCES agent_run(run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS agent_research_answer (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  run_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
  answer_sha256 CHAR(64) NOT NULL,
  citations_json JSON NOT NULL,
  unresolved_count INT NOT NULL,
  recorded_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_research_answer (user_id,run_id),
  CONSTRAINT fk_research_answer_run FOREIGN KEY (run_id) REFERENCES agent_run(run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
