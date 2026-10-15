-- 仅新增确认与审计表，不更新历史待确认操作，不自动执行旧动作。
CREATE TABLE IF NOT EXISTS agent_pending_action (
  action_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
  user_id BIGINT NOT NULL,
  run_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  session_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  call_id VARCHAR(160) COLLATE utf8mb4_bin DEFAULT NULL,
  operation VARCHAR(64) NOT NULL,
  resource_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  resource_version VARCHAR(64) NOT NULL,
  arguments_digest VARCHAR(64) NOT NULL,
  command_json JSON NOT NULL,
  before_json JSON NOT NULL,
  result_json JSON DEFAULT NULL,
  policy_version VARCHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  version BIGINT NOT NULL DEFAULT 1,
  reason_code VARCHAR(64) DEFAULT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  expires_at DATETIME(6) NOT NULL,
  decided_at DATETIME(6) DEFAULT NULL,
  PRIMARY KEY (action_id),
  UNIQUE KEY uk_action_request (user_id, run_id, arguments_digest),
  KEY idx_action_owner_session (user_id, session_id, created_at),
  KEY idx_action_owner_resource (user_id, resource_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_action_audit (
  id BIGINT NOT NULL AUTO_INCREMENT,
  action_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
  user_id BIGINT NOT NULL,
  run_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  event_type VARCHAR(64) NOT NULL,
  actor_role VARCHAR(24) NOT NULL,
  resource_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  arguments_digest VARCHAR(64) NOT NULL,
  policy_version VARCHAR(64) NOT NULL,
  result VARCHAR(24) NOT NULL,
  reason_code VARCHAR(64) DEFAULT NULL,
  occurred_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_action_audit_owner (user_id, action_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
