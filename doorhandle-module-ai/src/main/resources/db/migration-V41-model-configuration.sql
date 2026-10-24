-- V41: immutable model configuration snapshots; all credentials remain authenticated ciphertext.
CREATE TABLE IF NOT EXISTS agent_model_config_control (
 control_id INT PRIMARY KEY,
 active_revision BIGINT NOT NULL DEFAULT 0,
 sequence_value BIGINT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
INSERT IGNORE INTO agent_model_config_control(control_id) VALUES(1);
CREATE TABLE IF NOT EXISTS agent_model_configuration (
 revision BIGINT PRIMARY KEY,
 base_revision BIGINT NOT NULL,
 status VARCHAR(24) NOT NULL,
 document_json JSON NOT NULL,
 sealed_snapshot MEDIUMTEXT NOT NULL,
 memory_envelope MEDIUMTEXT NOT NULL,
 creator_user_id BIGINT NULL,
 request_id VARCHAR(128) NOT NULL,
 request_sha256 CHAR(64) NOT NULL,
 memory_state VARCHAR(24) NOT NULL DEFAULT 'PENDING',
 created_at DATETIME(6) NOT NULL,
 published_at DATETIME(6) NULL,
 UNIQUE KEY uk_model_config_request(creator_user_id,request_id),
 KEY idx_model_config_status(status,revision)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS agent_model_revoked_key (
 provider VARCHAR(24) NOT NULL,
 key_sha256 CHAR(64) NOT NULL,
 actor_user_id BIGINT NOT NULL,
 request_id VARCHAR(128) NOT NULL,
 memory_propagated BOOLEAN NOT NULL DEFAULT FALSE,
 created_at DATETIME(6) NOT NULL,
 PRIMARY KEY(provider,key_sha256)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS agent_model_json_probe (
 revision BIGINT NOT NULL,
 model_id VARCHAR(160) NOT NULL,
 request_id VARCHAR(128) NOT NULL,
 status VARCHAR(24) NOT NULL,
 created_at DATETIME(6) NOT NULL,
 PRIMARY KEY(revision,request_id),
 KEY idx_model_json_capability(revision,model_id,status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS agent_model_config_command (
 actor_user_id BIGINT NOT NULL,
 request_id VARCHAR(128) NOT NULL,
 action VARCHAR(32) NOT NULL,
 target VARCHAR(192) NOT NULL,
 revision BIGINT NOT NULL,
 created_at DATETIME(6) NOT NULL,
 PRIMARY KEY(actor_user_id,request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
