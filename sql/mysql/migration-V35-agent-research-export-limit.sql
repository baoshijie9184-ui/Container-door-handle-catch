-- Requires V33. One shared fixed-window counter per account; no source content.
CREATE TABLE IF NOT EXISTS agent_research_export_limit (
  user_id BIGINT NOT NULL,
  window_ends_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  export_count INT NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
