-- Requires V31. Additive governance tables only; does not erase any source content.
CREATE TABLE IF NOT EXISTS agent_research_storage_owner (
  user_id BIGINT NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS agent_research_content_purge (
  source_id VARCHAR(40) COLLATE utf8mb4_bin NOT NULL,
  user_id BIGINT NOT NULL,
  cleared_chars INT NOT NULL,
  purged_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (source_id),
  KEY idx_research_purge_owner (user_id,purged_at),
  CONSTRAINT fk_research_purge_source FOREIGN KEY (source_id) REFERENCES agent_research_source(source_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
