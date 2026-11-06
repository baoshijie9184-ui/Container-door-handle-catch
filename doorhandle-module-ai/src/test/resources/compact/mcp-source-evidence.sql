-- Exact original MCP DDL/ALTER; authored from checked-in declarations.
CREATE TABLE IF NOT EXISTS agent_local_mcp (
  id BIGINT NOT NULL AUTO_INCREMENT, owner_user_id BIGINT NOT NULL, server_key VARCHAR(32) NOT NULL,
  package_version VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'NOT_INSTALLED',
  enabled BOOLEAN NOT NULL DEFAULT FALSE, revision INT NOT NULL DEFAULT 0,
  operation_id VARCHAR(64) NULL, request_id VARCHAR(64) NULL, lease_expires_at DATETIME NULL,
  manifest_json JSON NULL, manifest_sha256 CHAR(64) NULL, error_code VARCHAR(64) NULL,
  created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
  PRIMARY KEY(id), UNIQUE KEY uk_local_mcp_owner(owner_user_id,server_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS agent_local_mcp_audit (
  id BIGINT NOT NULL AUTO_INCREMENT, owner_user_id BIGINT NOT NULL, server_key VARCHAR(32) NOT NULL,
  action_name VARCHAR(32) NOT NULL, outcome VARCHAR(32) NOT NULL, revision INT NOT NULL,
  operation_id VARCHAR(64) NULL, run_id VARCHAR(128) NULL, call_id VARCHAR(160) NULL,
  detail_json JSON NOT NULL, created_at DATETIME NOT NULL,
  PRIMARY KEY(id), KEY idx_local_mcp_audit_owner(owner_user_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS agent_mcp_install_job (
  id BIGINT NOT NULL AUTO_INCREMENT,
  operation_id VARCHAR(64) NOT NULL,
  owner_user_id BIGINT NOT NULL,
  owner_username VARCHAR(128) NOT NULL,
  runtime_sha256 CHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'QUEUED',
  worker_token VARCHAR(64) NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  PRIMARY KEY(id),
  UNIQUE KEY uk_mcp_install_operation(operation_id),
  KEY idx_mcp_install_pending(status,id),
  KEY idx_mcp_install_owner(owner_user_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS agent_mcp_execution (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 execution_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
 owner_user_id BIGINT NOT NULL,
 installation_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
 runtime_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 pool_id CHAR(32) COLLATE utf8mb4_bin NOT NULL,
 purpose VARCHAR(16) NOT NULL,
 state VARCHAR(24) NOT NULL,
 revision INT NOT NULL DEFAULT 0,
 exit_verified BOOLEAN NOT NULL DEFAULT FALSE,
 cleanup_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
 run_id VARCHAR(128) NULL,
 call_id VARCHAR(160) NULL,
 lease_expires_at DATETIME(6) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_mcp_execution(execution_id),
 KEY idx_mcp_execution_owner(owner_user_id,state,id),
 KEY idx_mcp_execution_installation(owner_user_id,installation_id,state),
 KEY idx_mcp_execution_expiry(state,lease_expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_mcp_execution_command (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 owner_user_id BIGINT NOT NULL,
 request_id VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
 execution_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
 request_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 status VARCHAR(24) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_mcp_execution_request(owner_user_id,request_id),
 KEY idx_mcp_execution_command(owner_user_id,execution_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_fetch_installation (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 owner_user_id BIGINT NOT NULL,
 installation_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
 prior_installation_id VARCHAR(36) COLLATE utf8mb4_bin NULL,
 state VARCHAR(24) NOT NULL,
 revision INT NOT NULL DEFAULT 0,
 writer_exit_verified BOOLEAN NOT NULL DEFAULT FALSE,
 retained_for_rollback BOOLEAN NOT NULL DEFAULT FALSE,
 package_version VARCHAR(64) NOT NULL,
 transport VARCHAR(32) NOT NULL,
 image_id VARCHAR(80) NULL,
 manifest_json JSON NULL,
 manifest_sha256 CHAR(64) COLLATE utf8mb4_bin NULL,
 cleanup_request VARCHAR(64) COLLATE utf8mb4_bin NULL,
 cleanup_expires_at DATETIME(6) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_fetch_installation(owner_user_id,installation_id),
 KEY idx_fetch_installation_state(owner_user_id,state,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_fetch_lifecycle_command (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 owner_user_id BIGINT NOT NULL,
 request_id VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
 installation_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
 action_name VARCHAR(24) NOT NULL,
 request_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 status VARCHAR(24) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_fetch_lifecycle_request(owner_user_id,request_id),
 KEY idx_fetch_lifecycle_install(owner_user_id,installation_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
ALTER TABLE agent_mcp_execution ADD COLUMN transport VARCHAR(32) NOT NULL DEFAULT 'STREAMABLE_HTTP';
ALTER TABLE agent_fetch_installation
 ADD COLUMN reconcile_request VARCHAR(64) COLLATE utf8mb4_bin NULL,
 ADD COLUMN reconcile_expires_at DATETIME(6) NULL,
 ADD COLUMN writer_evidence_code VARCHAR(48) NULL;
CREATE TABLE IF NOT EXISTS agent_mcp_install_worker (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 owner_user_id BIGINT NOT NULL,
 installation_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
 node_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 runtime_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 controller_pid BIGINT NOT NULL,
 controller_started VARCHAR(48) NOT NULL,
 container_id CHAR(64) COLLATE utf8mb4_bin NULL,
 container_started VARCHAR(64) NULL,
 controller_pool_id CHAR(32) COLLATE utf8mb4_bin NULL,
 state VARCHAR(24) NOT NULL,
 revision INT NOT NULL DEFAULT 0,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_mcp_install_worker(owner_user_id,installation_id),
 KEY idx_mcp_install_worker_state(owner_user_id,state,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
ALTER TABLE agent_mcp_install_worker
 ADD COLUMN writer_transport VARCHAR(32) NOT NULL DEFAULT 'STREAMABLE_HTTP',
 ADD COLUMN native_pool_id CHAR(32) COLLATE utf8mb4_bin NULL;
ALTER TABLE agent_fetch_installation
 ADD COLUMN reserved_bytes BIGINT NOT NULL DEFAULT 2097152;
CREATE TABLE IF NOT EXISTS agent_fetch_image (
 image_id VARCHAR(80) COLLATE utf8mb4_bin NOT NULL PRIMARY KEY,
 state VARCHAR(24) NOT NULL DEFAULT 'ACTIVE',
 revision INT NOT NULL DEFAULT 0,
 cleanup_request VARCHAR(36) COLLATE utf8mb4_bin NULL,
 cleanup_owner_user_id BIGINT NULL,
 runner_pool_id CHAR(32) COLLATE utf8mb4_bin NULL,
 archive_sha256 CHAR(64) COLLATE utf8mb4_bin NULL,
 image_absent BOOLEAN NOT NULL DEFAULT FALSE,
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_fetch_image_command (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 owner_user_id BIGINT NOT NULL,
 request_id VARCHAR(36) COLLATE utf8mb4_bin NOT NULL,
 image_id VARCHAR(80) COLLATE utf8mb4_bin NOT NULL,
 request_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 action_name VARCHAR(16) NOT NULL,
 state VARCHAR(24) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_fetch_image_request(owner_user_id,request_id),
 KEY idx_fetch_image_command(image_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
ALTER TABLE agent_mcp_execution ADD COLUMN image_id VARCHAR(80) COLLATE utf8mb4_bin NULL;
ALTER TABLE agent_fetch_image_command ADD COLUMN retention_protocol INT NOT NULL DEFAULT 3;
CREATE TABLE IF NOT EXISTS agent_fetch_image_retention (
 reference_id VARCHAR(96) COLLATE utf8mb4_bin NOT NULL,
 image_id VARCHAR(80) COLLATE utf8mb4_bin NOT NULL,
 reference_kind VARCHAR(24) NOT NULL,
 state VARCHAR(16) NOT NULL DEFAULT 'HELD',
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 PRIMARY KEY(reference_id,image_id),
 KEY idx_fetch_image_retention(image_id,state)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_fetch_image_retention_control (
 control_id TINYINT NOT NULL PRIMARY KEY,
 state VARCHAR(16) NOT NULL DEFAULT 'COLLECTING',
 revision BIGINT NOT NULL DEFAULT 0,
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT IGNORE INTO agent_fetch_image_retention_control(control_id,state) VALUES(1,'COLLECTING');
CREATE TABLE IF NOT EXISTS agent_fetch_image_retention_event (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 request_id CHAR(32) COLLATE utf8mb4_bin NOT NULL,
 action_name VARCHAR(24) NOT NULL,
 image_id VARCHAR(80) COLLATE utf8mb4_bin NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_fetch_retention_event(request_id,action_name,image_id),
 KEY idx_fetch_retention_event(request_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
