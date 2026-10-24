-- Additive private context store. No original chat/tool records are rewritten or deleted.
CREATE TABLE IF NOT EXISTS agent_context_head (
 user_id BIGINT NOT NULL,
 session_id VARCHAR(128) NOT NULL,
 agent_scope VARCHAR(160) NOT NULL,
 revision BIGINT NOT NULL DEFAULT 0,
 summary_id VARCHAR(36) NULL,
 PRIMARY KEY(user_id,session_id,agent_scope)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS agent_context_summary (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 summary_id VARCHAR(36) NOT NULL,
 user_id BIGINT NOT NULL,
 session_id VARCHAR(128) NOT NULL,
 agent_scope VARCHAR(160) NOT NULL,
 revision BIGINT NOT NULL,
 status VARCHAR(24) NOT NULL,
 covered_through BIGINT NOT NULL,
 history_sha256 CHAR(64) NOT NULL,
 summary_json MEDIUMTEXT NOT NULL,
 summary_sha256 CHAR(64) NOT NULL,
 message_state MEDIUMTEXT NOT NULL,
 sources_json MEDIUMTEXT NOT NULL,
 policy_version VARCHAR(64) NOT NULL,
 run_id VARCHAR(128) NOT NULL,
 before_chars BIGINT NOT NULL,
 after_chars BIGINT NOT NULL,
 original_state MEDIUMTEXT NOT NULL,
 created_at DATETIME(6) NOT NULL,
 UNIQUE KEY uk_context_summary(summary_id),
 UNIQUE KEY uk_context_revision(user_id,session_id,agent_scope,revision),
 KEY idx_context_fork(user_id,session_id,agent_scope,covered_through)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS agent_context_offload (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 offload_id VARCHAR(36) NOT NULL,
 user_id BIGINT NOT NULL,
 session_id VARCHAR(128) NOT NULL,
 agent_scope VARCHAR(160) NOT NULL,
 call_id VARCHAR(160) NOT NULL,
 file_id VARCHAR(36) NOT NULL,
 content_sha256 CHAR(64) NOT NULL,
 byte_length BIGINT NOT NULL,
 sources_json MEDIUMTEXT NOT NULL,
 sources_sha256 CHAR(64) NOT NULL,
 created_at DATETIME(6) NOT NULL,
 UNIQUE KEY uk_context_offload(offload_id),
 UNIQUE KEY uk_context_call(user_id,session_id,agent_scope,call_id),
 KEY idx_context_file(user_id,session_id,file_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS agent_context_audit (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 user_id BIGINT NOT NULL,
 session_id VARCHAR(128) NOT NULL,
 agent_scope VARCHAR(160) NOT NULL,
 resource_id VARCHAR(36) NOT NULL,
 action VARCHAR(64) NOT NULL,
 content_sha256 CHAR(64) NOT NULL,
 created_at DATETIME(6) NOT NULL,
 KEY idx_context_audit_owner(user_id,session_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS agent_context_origin (
 user_id BIGINT NOT NULL,
 session_id VARCHAR(128) NOT NULL,
 agent_scope VARCHAR(160) NOT NULL,
 call_key CHAR(64) NOT NULL,
 logical_task_id VARCHAR(36) NOT NULL,
 run_id VARCHAR(128) NOT NULL,
 sources_json MEDIUMTEXT NOT NULL,
 sources_sha256 CHAR(64) NOT NULL,
 PRIMARY KEY(user_id,session_id,agent_scope,call_key),
 KEY idx_context_origin_task(user_id,session_id,logical_task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS agent_context_turn (
 user_id BIGINT NOT NULL,
 session_id VARCHAR(128) NOT NULL,
 message_id BIGINT NOT NULL,
 sources_json MEDIUMTEXT NOT NULL,
 sources_sha256 CHAR(64) NOT NULL,
 PRIMARY KEY(user_id,session_id,message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS agent_context_bootstrap (
 user_id BIGINT NOT NULL,
 session_id VARCHAR(128) NOT NULL,
 logical_task_id VARCHAR(36) NOT NULL,
 agent_scope VARCHAR(160) NOT NULL,
 history_through BIGINT NOT NULL,
 initial_state MEDIUMTEXT NOT NULL,
 initial_sha256 CHAR(64) NOT NULL,
 initialized TINYINT NOT NULL DEFAULT 0,
 PRIMARY KEY(user_id,session_id,logical_task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
