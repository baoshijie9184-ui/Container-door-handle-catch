-- AgentScope 单体运行与事件记录，仅创建新表，不修改或清空旧聊天数据。
CREATE TABLE IF NOT EXISTS agent_run (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  run_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
  user_id BIGINT NOT NULL,
  session_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  main_agent VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
  entry_point VARCHAR(16) COLLATE utf8mb4_bin NOT NULL,
  request_key VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  status VARCHAR(16) NOT NULL,
  default_model VARCHAR(160) NOT NULL,
  policy_version VARCHAR(64) NOT NULL,
  instance_id VARCHAR(36) NOT NULL,
  active_slot TINYINT NULL,
  last_sequence BIGINT NOT NULL DEFAULT 0,
  started_at DATETIME(6) NOT NULL,
  ended_at DATETIME(6) NULL,
  heartbeat_at DATETIME(6) NOT NULL,
  lease_expires_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_agent_run_id (run_id),
  UNIQUE KEY uk_agent_run_request (user_id,entry_point,request_key),
  UNIQUE KEY uk_agent_session_active (user_id,main_agent,session_id,active_slot),
  KEY idx_agent_run_owner (user_id,id),
  KEY idx_agent_run_session (user_id,session_id,id),
  KEY idx_agent_run_expiry (status,lease_expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS agent_run_event (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  run_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
  user_id BIGINT NOT NULL,
  sequence_no BIGINT NOT NULL,
  event_type VARCHAR(64) NOT NULL,
  occurred_at DATETIME(6) NOT NULL,
  payload_json JSON NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_agent_event_sequence (run_id,sequence_no),
  KEY idx_agent_event_owner (user_id,run_id,sequence_no),
  CONSTRAINT fk_agent_event_run FOREIGN KEY (run_id) REFERENCES agent_run(run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
