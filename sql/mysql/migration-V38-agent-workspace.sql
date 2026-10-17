-- App-owned user file metadata and conversation lineage; file bytes remain on the existing private volume.
CREATE TABLE IF NOT EXISTS agent_workspace_owner (
  user_id BIGINT NOT NULL PRIMARY KEY
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_workspace_file (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  file_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
  user_id BIGINT NOT NULL,
  request_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  filename VARCHAR(240) NOT NULL,
  content_type VARCHAR(100) NOT NULL,
  byte_length BIGINT NOT NULL,
  sha256 CHAR(64) NOT NULL,
  folder VARCHAR(32) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uk_workspace_file(file_id),
  UNIQUE KEY uk_workspace_request(user_id,request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_workspace_file_ref (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  session_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  file_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uk_workspace_ref(user_id,session_id,file_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_workspace_request (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  request_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  signature CHAR(64) NOT NULL,
  UNIQUE KEY uk_workspace_mutation(user_id,request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_session_fork (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  request_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  source_session_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  through_message_id BIGINT NOT NULL,
  fork_session_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  UNIQUE KEY uk_session_fork_request(user_id,request_id),
  UNIQUE KEY uk_session_fork_child(fork_session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_workspace_audit (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  session_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  resource_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  action VARCHAR(32) NOT NULL,
  content_sha256 CHAR(64) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  KEY ix_workspace_audit(user_id,session_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_workspace_business_ref (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  session_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  kind VARCHAR(20) NOT NULL,
  resource_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uk_workspace_business(user_id,session_id,kind,resource_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
