-- Eight dedicated conversation, execution, connector and LLM tables.
-- Part of the accepted compact model. Fresh target only; not a source upgrade.

CREATE TABLE chat_project (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 project_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL,
 username VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL,
 user_id BIGINT NOT NULL,
 name VARCHAR(100) COLLATE utf8mb4_unicode_ci NOT NULL,
 description VARCHAR(500) COLLATE utf8mb4_unicode_ci NULL,
 color VARCHAR(20) COLLATE utf8mb4_unicode_ci DEFAULT '#4f6ef7',
 sort_order INT DEFAULT 0,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
 UNIQUE KEY uq_chat_project_id(project_id),
 UNIQUE KEY uq_chat_project_owner(user_id,project_id),
 KEY ix_chat_project_username(username),
 KEY ix_chat_project_order(user_id,sort_order,created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE chat_session (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 session_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL,
 username VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL,
 user_id BIGINT NOT NULL,
 project_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NULL,
 title VARCHAR(255) COLLATE utf8mb4_unicode_ci NULL,
 status VARCHAR(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'ACTIVE',
 pinned BOOLEAN DEFAULT FALSE,
 state_json LONGTEXT COLLATE utf8mb4_unicode_ci NULL,
 checkpoint_version INT NOT NULL DEFAULT 0,
 checkpoint_node VARCHAR(64) COLLATE utf8mb4_unicode_ci NULL,
 checkpoint_exit_reason VARCHAR(64) COLLATE utf8mb4_unicode_ci NULL,
 checkpoint_updated_at DATETIME NULL,
 fork_owner_user_id BIGINT NULL,
 fork_request_id VARCHAR(128) NULL,
 fork_source_session_id VARCHAR(128) NULL,
 fork_through_message_id BIGINT NULL,
 fork_legacy_id BIGINT UNSIGNED NULL,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
 UNIQUE KEY uq_chat_session_id(session_id),
 UNIQUE KEY uq_chat_session_owner(user_id,session_id),
 UNIQUE KEY uq_chat_session_fork(fork_owner_user_id,fork_request_id),
 UNIQUE KEY uq_chat_session_fork_legacy(fork_legacy_id),
 KEY ix_chat_session_project(project_id),
 KEY ix_chat_session_username(username,status,pinned,updated_at),
 KEY ix_chat_session_owner_list(user_id,status,pinned,updated_at),
 KEY ix_chat_session_checkpoint(checkpoint_updated_at),
 CONSTRAINT ck_chat_session_state CHECK (state_json IS NULL OR JSON_VALID(state_json)),
 CONSTRAINT ck_chat_session_fork CHECK (
  (fork_owner_user_id IS NULL AND fork_request_id IS NULL AND fork_source_session_id IS NULL AND fork_through_message_id IS NULL AND fork_legacy_id IS NULL)
  OR (fork_owner_user_id IS NOT NULL AND fork_request_id IS NOT NULL AND fork_source_session_id IS NOT NULL AND fork_through_message_id IS NOT NULL AND fork_owner_user_id=user_id))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE chat_message (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 session_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL,
 role VARCHAR(16) COLLATE utf8mb4_unicode_ci NOT NULL,
 message_type VARCHAR(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'TEXT',
 content LONGTEXT COLLATE utf8mb4_unicode_ci NOT NULL,
 intent VARCHAR(64) COLLATE utf8mb4_unicode_ci NULL,
 action_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NULL,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 execution_run_id VARCHAR(36) NULL,
 execution_owner_user_id BIGINT NULL,
 execution_created_at DATETIME(6) NULL,
 execution_legacy_id BIGINT UNSIGNED NULL,
 execution_evidence_id BIGINT UNSIGNED NULL,
 snapshot_owner_user_id BIGINT NULL,
 workspace_snapshot_json MEDIUMTEXT NULL,
 workspace_snapshot_sha256 CHAR(64) NULL,
 workspace_snapshot_created_at DATETIME(6) NULL,
 workspace_snapshot_legacy_id BIGINT UNSIGNED NULL,
 snapshot_evidence_id BIGINT UNSIGNED NULL,
 context_owner_user_id BIGINT NULL,
 context_sources_json MEDIUMTEXT NULL,
 context_sources_sha256 CHAR(64) NULL,
 context_evidence_id BIGINT UNSIGNED NULL,
 KEY ix_chat_message_session(session_id,id),
 UNIQUE KEY uq_chat_message_execution(execution_run_id),
 UNIQUE KEY uq_chat_message_execution_legacy(execution_legacy_id),
 UNIQUE KEY uq_chat_message_snapshot_legacy(workspace_snapshot_legacy_id),
 CONSTRAINT ck_chat_message_execution CHECK (
  (execution_run_id IS NULL AND execution_owner_user_id IS NULL AND execution_created_at IS NULL AND execution_legacy_id IS NULL AND execution_evidence_id IS NULL)
  OR (execution_run_id IS NOT NULL AND execution_owner_user_id IS NOT NULL AND execution_created_at IS NOT NULL AND execution_evidence_id IS NOT NULL)),
 CONSTRAINT ck_chat_message_snapshot CHECK (
  (snapshot_owner_user_id IS NULL AND workspace_snapshot_json IS NULL AND workspace_snapshot_sha256 IS NULL AND workspace_snapshot_created_at IS NULL AND workspace_snapshot_legacy_id IS NULL AND snapshot_evidence_id IS NULL)
  OR (snapshot_owner_user_id IS NOT NULL AND workspace_snapshot_json IS NOT NULL AND workspace_snapshot_sha256 IS NOT NULL AND workspace_snapshot_created_at IS NOT NULL AND snapshot_evidence_id IS NOT NULL AND JSON_VALID(workspace_snapshot_json))),
 CONSTRAINT ck_chat_message_sources CHECK (
  (context_owner_user_id IS NULL AND context_sources_json IS NULL AND context_sources_sha256 IS NULL AND context_evidence_id IS NULL)
  OR (context_owner_user_id IS NOT NULL AND context_sources_json IS NOT NULL AND context_sources_sha256 IS NOT NULL AND context_evidence_id IS NOT NULL AND JSON_VALID(context_sources_json)))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE agent_run (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 run_id VARCHAR(36) NOT NULL,
 user_id BIGINT NOT NULL,
 session_id VARCHAR(128) NOT NULL,
 main_agent VARCHAR(64) NOT NULL,
 entry_point VARCHAR(16) NOT NULL,
 request_key VARCHAR(128) NOT NULL,
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
 answer_owner_user_id BIGINT NULL,
 answer_sha256 CHAR(64) NULL,
 answer_citations_json JSON NULL,
 answer_unresolved_count INT NULL,
 answer_recorded_at DATETIME(6) NULL,
 answer_legacy_id BIGINT UNSIGNED NULL,
 UNIQUE KEY uq_agent_run_id(run_id),
 UNIQUE KEY uq_agent_run_owner(user_id,run_id),
 UNIQUE KEY uq_agent_run_owner_session(user_id,session_id,run_id),
 UNIQUE KEY uq_agent_run_request(user_id,entry_point,request_key),
 UNIQUE KEY uq_agent_run_active(user_id,main_agent,session_id,active_slot),
 UNIQUE KEY uq_agent_run_answer_legacy(answer_legacy_id),
 KEY ix_agent_run_owner(user_id,id),
 KEY ix_agent_run_session(user_id,session_id,id),
 KEY ix_agent_run_expiry(status,lease_expires_at),
 CONSTRAINT ck_agent_run_answer CHECK (
  (answer_owner_user_id IS NULL AND answer_sha256 IS NULL AND answer_citations_json IS NULL AND answer_unresolved_count IS NULL AND answer_recorded_at IS NULL AND answer_legacy_id IS NULL)
  OR (answer_owner_user_id IS NOT NULL AND answer_owner_user_id=user_id AND answer_sha256 IS NOT NULL AND answer_citations_json IS NOT NULL AND answer_unresolved_count IS NOT NULL AND answer_unresolved_count>=0 AND answer_recorded_at IS NOT NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Registration only. Installation versions and process attempts use workflows.
CREATE TABLE agent_connector (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 owner_user_id BIGINT NOT NULL,
 server_key VARCHAR(32) NOT NULL,
 package_version VARCHAR(64) NOT NULL,
 status VARCHAR(32) NOT NULL DEFAULT 'NOT_INSTALLED',
 enabled BOOLEAN NOT NULL DEFAULT FALSE,
 revision INT NOT NULL DEFAULT 0,
 operation_id VARCHAR(64) NULL,
 request_id VARCHAR(64) NULL,
 lease_expires_at DATETIME NULL,
 manifest_json JSON NULL,
 manifest_sha256 CHAR(64) NULL,
 error_code VARCHAR(64) NULL,
 current_installation_id VARCHAR(64) NULL,
 created_at DATETIME NOT NULL,
 updated_at DATETIME NOT NULL,
 UNIQUE KEY uq_agent_connector_owner(owner_user_id,server_key),
 KEY ix_agent_connector_status(status,lease_expires_at),
 CONSTRAINT ck_agent_connector_revision CHECK (revision>=0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE llm_configuration (
 revision BIGINT NOT NULL PRIMARY KEY,
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
 UNIQUE KEY uq_llm_configuration_request(creator_user_id,request_id),
 KEY ix_llm_configuration_status(status,revision),
 CONSTRAINT ck_llm_configuration_revision CHECK (revision>0 AND base_revision>=0),
 CONSTRAINT ck_llm_configuration_status CHECK (status IN ('DRAFT','VALIDATED','PUBLISHED','RETIRED')),
 CONSTRAINT ck_llm_configuration_memory CHECK (memory_state IN ('PENDING','ENVIRONMENT','APPLIED')),
 CONSTRAINT ck_llm_configuration_owner CHECK (creator_user_id IS NULL OR creator_user_id>0),
 CONSTRAINT ck_llm_configuration_request CHECK (CHAR_LENGTH(request_id)>0 AND request_sha256 REGEXP '^[a-f0-9]{64}$')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- MODEL scope is the single enterprise's per-model account. Absence of a USER
-- account preserves existing model access; a NULL limit is explicitly unlimited.
CREATE TABLE llm_quota (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 scope_type VARCHAR(16) NOT NULL,
 owner_user_id BIGINT NULL,
 subject_key BIGINT GENERATED ALWAYS AS (COALESCE(owner_user_id,0)) VIRTUAL,
 model_id VARCHAR(180) COLLATE utf8mb4_0900_ai_ci NOT NULL,
 period_key VARCHAR(40) NOT NULL DEFAULT 'TOTAL',
 total_tokens BIGINT NULL,
 reserved_tokens BIGINT NOT NULL DEFAULT 0,
 spent_tokens BIGINT NOT NULL DEFAULT 0,
 unreconciled_legacy_attempts BIGINT NOT NULL DEFAULT 0,
 warning_percent INT NOT NULL DEFAULT 80,
 free_only BOOLEAN NOT NULL DEFAULT TRUE,
 expires_at DATETIME(6) NULL,
 version BIGINT NOT NULL DEFAULT 1,
 updated_by BIGINT NULL,
 created_at DATETIME(6) NOT NULL,
 updated_at DATETIME(6) NOT NULL,
 UNIQUE KEY uq_llm_quota_account(scope_type,subject_key,model_id,period_key),
 KEY ix_llm_quota_model(model_id,scope_type),
 CONSTRAINT ck_llm_quota_scope CHECK ((scope_type='MODEL' AND owner_user_id IS NULL) OR (scope_type='USER' AND owner_user_id IS NOT NULL AND owner_user_id>0)),
 CONSTRAINT ck_llm_quota_numbers CHECK ((total_tokens IS NULL OR total_tokens>=0) AND reserved_tokens>=0 AND spent_tokens>=0 AND unreconciled_legacy_attempts>=0 AND version>=0),
 CONSTRAINT ck_llm_quota_legacy_scope CHECK (scope_type='MODEL' OR unreconciled_legacy_attempts=0),
 CONSTRAINT ck_llm_quota_warning CHECK (warning_percent BETWEEN 1 AND 100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Accounting entries only. Request/attempt/lease states live in workflows.
-- Account updates and the corresponding entries must commit in one transaction.
CREATE TABLE llm_usage (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 account_id BIGINT UNSIGNED NOT NULL,
 root_operation_id BIGINT UNSIGNED NULL,
 operation_id BIGINT UNSIGNED NULL,
 source_audit_event_id BIGINT UNSIGNED NULL,
 entry_key VARCHAR(128) NOT NULL,
 entry_type VARCHAR(24) NOT NULL,
 reserved_delta BIGINT NOT NULL DEFAULT 0,
 spent_delta BIGINT NOT NULL DEFAULT 0,
 limit_before BIGINT NULL,
 limit_after BIGINT NULL,
 input_tokens BIGINT NULL,
 output_tokens BIGINT NULL,
 cached_tokens BIGINT NULL,
 request_sha256 CHAR(64) NOT NULL,
 actor_user_id BIGINT NULL,
 created_at DATETIME(6) NOT NULL,
 UNIQUE KEY uq_llm_usage_operation(account_id,operation_id,entry_key),
 UNIQUE KEY uq_llm_usage_import(account_id,source_audit_event_id,entry_key),
 KEY ix_llm_usage_root(account_id,root_operation_id,id),
 KEY ix_llm_usage_operation(operation_id),
 KEY ix_llm_usage_created(account_id,created_at,id),
 CONSTRAINT ck_llm_usage_type CHECK (entry_type IN ('RESERVE','SETTLE','RELEASE','LIMIT_CHANGE','IMPORTED_USAGE','VOID')),
 CONSTRAINT ck_llm_usage_origin CHECK ((entry_type='IMPORTED_USAGE' AND root_operation_id IS NULL AND operation_id IS NULL AND source_audit_event_id IS NOT NULL AND actor_user_id IS NULL)
     OR (entry_type<>'IMPORTED_USAGE' AND root_operation_id IS NOT NULL AND operation_id IS NOT NULL AND source_audit_event_id IS NULL)),
 CONSTRAINT ck_llm_usage_import CHECK (entry_type<>'IMPORTED_USAGE' OR (reserved_delta=0 AND spent_delta=COALESCE(input_tokens,0)+COALESCE(output_tokens,0) AND limit_before IS NULL AND limit_after IS NULL)),
 CONSTRAINT ck_llm_usage_numbers CHECK ((input_tokens IS NULL OR input_tokens>=0) AND (output_tokens IS NULL OR output_tokens>=0) AND (cached_tokens IS NULL OR cached_tokens>=0) AND spent_delta>=0 AND (limit_before IS NULL OR limit_before>=0) AND (limit_after IS NULL OR limit_after>=0)),
 CONSTRAINT ck_llm_usage_reserve CHECK (entry_type<>'RESERVE' OR (reserved_delta>0 AND spent_delta=0)),
 CONSTRAINT ck_llm_usage_settle CHECK (entry_type<>'SETTLE' OR (reserved_delta<=0 AND input_tokens IS NOT NULL AND output_tokens IS NOT NULL AND spent_delta=input_tokens+output_tokens)),
 CONSTRAINT ck_llm_usage_release CHECK (entry_type<>'RELEASE' OR (reserved_delta<0 AND spent_delta=0)),
 CONSTRAINT ck_llm_usage_nonusage CHECK (entry_type NOT IN ('LIMIT_CHANGE','VOID') OR (reserved_delta=0 AND spent_delta=0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
