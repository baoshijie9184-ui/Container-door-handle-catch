-- Account-private workbench metadata. Requires V16 and V36. Does not migrate legacy trace JSON.
CREATE TABLE IF NOT EXISTS agent_workbench_owner (
  user_id BIGINT NOT NULL PRIMARY KEY
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_workbench_item (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  item_id VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
  user_id BIGINT NOT NULL,
  session_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  kind VARCHAR(32) NOT NULL,
  status VARCHAR(40) NOT NULL,
  revision BIGINT NOT NULL DEFAULT 0,
  payload LONGTEXT NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uk_workbench_item(item_id),
  KEY ix_workbench_session(user_id,session_id,id),
  KEY ix_workbench_dispatch(kind,status,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_workbench_audit (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  session_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  item_id VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
  action VARCHAR(48) NOT NULL,
  revision BIGINT NOT NULL,
  payload_sha256 CHAR(64) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  KEY ix_workbench_audit(user_id,session_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_workbench_request (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  request_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  request_sha256 CHAR(64) NOT NULL,
  result_json LONGTEXT NOT NULL,
  UNIQUE KEY uk_workbench_request(user_id,request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_workbench_sdk_state (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id VARCHAR(32) COLLATE utf8mb4_bin NOT NULL,
  session_id VARCHAR(160) COLLATE utf8mb4_bin NOT NULL,
  state_key VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  revision BIGINT NOT NULL,
  state_json LONGTEXT NOT NULL,
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uk_workbench_sdk(user_id,session_id,state_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
