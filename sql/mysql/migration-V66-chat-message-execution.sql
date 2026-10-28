-- Explicit migration only. Preserve legacy messages; never infer a run from timestamps or text.
CREATE TABLE IF NOT EXISTS agent_message_execution (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  session_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  message_id BIGINT NOT NULL,
  run_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uk_message_execution_message(message_id),
  UNIQUE KEY uk_message_execution_run(run_id),
  KEY idx_message_execution_owner(user_id,session_id,message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
