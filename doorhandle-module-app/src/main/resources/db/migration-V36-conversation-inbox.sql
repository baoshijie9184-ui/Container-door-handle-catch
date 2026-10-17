-- Requires the existing chat_session/chat_message tables and V16 Agent journal.
CREATE TABLE IF NOT EXISTS agent_conversation_input_owner (
  user_id BIGINT NOT NULL,
  PRIMARY KEY (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS agent_conversation_input (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  input_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
  user_id BIGINT NOT NULL,
  username VARCHAR(128) NOT NULL,
  session_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  mode VARCHAR(24) NOT NULL,
  requested_mode VARCHAR(24) NOT NULL,
  entry_point VARCHAR(8) NOT NULL DEFAULT 'CHAT',
  target_run_id VARCHAR(36) COLLATE utf8mb4_bin DEFAULT NULL,
  status VARCHAR(24) NOT NULL DEFAULT 'QUEUED',
  revision INT NOT NULL DEFAULT 0,
  content TEXT NOT NULL,
  content_sha256 CHAR(64) NOT NULL,
  active_slot TINYINT DEFAULT NULL,
  expires_at DATETIME(6) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_conversation_input (input_id),
  UNIQUE KEY uk_conversation_input_active (user_id,session_id,active_slot),
  KEY idx_conversation_input_queue (status,id),
  KEY idx_conversation_input_owner (user_id,session_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS agent_conversation_input_audit (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  input_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
  user_id BIGINT NOT NULL,
  action VARCHAR(32) NOT NULL,
  revision INT NOT NULL,
  content_sha256 CHAR(64) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_conversation_input_audit_owner (user_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
