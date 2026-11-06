-- Compact chat aggregate, MySQL 8.4. Run once on an isolated, stopped-writer
-- clone. The following copy script must finish before starting compact code.
-- Historic V38/V44/V45/V66 scripts remain immutable. No old table is dropped.
ALTER TABLE chat_message
    ADD COLUMN execution_run_id VARCHAR(36) COLLATE utf8mb4_bin NULL,
    ADD COLUMN execution_owner_user_id BIGINT NULL,
    ADD COLUMN execution_created_at DATETIME(6) NULL,
    ADD COLUMN execution_legacy_id BIGINT UNSIGNED NULL,
    ADD COLUMN snapshot_owner_user_id BIGINT NULL,
    ADD COLUMN workspace_snapshot_json MEDIUMTEXT NULL,
    ADD COLUMN workspace_snapshot_sha256 CHAR(64) COLLATE utf8mb4_bin NULL,
    ADD COLUMN workspace_snapshot_created_at DATETIME(6) NULL,
    ADD COLUMN workspace_snapshot_legacy_id BIGINT UNSIGNED NULL,
    ADD COLUMN context_owner_user_id BIGINT NULL,
    ADD COLUMN context_sources_json MEDIUMTEXT NULL,
    ADD COLUMN context_sources_sha256 CHAR(64) COLLATE utf8mb4_bin NULL,
    ADD CONSTRAINT uk_chat_message_execution_run UNIQUE(execution_run_id),
    ADD CONSTRAINT uk_chat_message_execution_legacy UNIQUE(execution_legacy_id),
    ADD CONSTRAINT uk_chat_message_snapshot_legacy UNIQUE(workspace_snapshot_legacy_id),
    ADD CONSTRAINT ck_chat_message_execution CHECK (
        (execution_run_id IS NULL AND execution_owner_user_id IS NULL AND execution_created_at IS NULL AND execution_legacy_id IS NULL)
        OR (execution_run_id IS NOT NULL AND execution_owner_user_id IS NOT NULL AND execution_created_at IS NOT NULL)),
    ADD CONSTRAINT ck_chat_message_snapshot CHECK (
        (snapshot_owner_user_id IS NULL AND workspace_snapshot_json IS NULL AND workspace_snapshot_sha256 IS NULL
            AND workspace_snapshot_created_at IS NULL AND workspace_snapshot_legacy_id IS NULL)
        OR (snapshot_owner_user_id IS NOT NULL AND workspace_snapshot_json IS NOT NULL AND workspace_snapshot_sha256 IS NOT NULL
            AND workspace_snapshot_created_at IS NOT NULL AND JSON_VALID(workspace_snapshot_json))),
    ADD CONSTRAINT ck_chat_message_context_sources CHECK (
        (context_owner_user_id IS NULL AND context_sources_json IS NULL AND context_sources_sha256 IS NULL)
        OR (context_owner_user_id IS NOT NULL AND context_sources_json IS NOT NULL AND context_sources_sha256 IS NOT NULL
            AND JSON_VALID(context_sources_json)));

-- Lineage is part of a surviving session. Its request receipt is independent
-- in operation_job, so deleting a child cannot release the request identity.
ALTER TABLE chat_session
    ADD COLUMN fork_owner_user_id BIGINT NULL,
    ADD COLUMN fork_request_id VARCHAR(128) COLLATE utf8mb4_bin NULL,
    ADD COLUMN fork_source_session_id VARCHAR(128) COLLATE utf8mb4_bin NULL,
    ADD COLUMN fork_through_message_id BIGINT NULL,
    ADD COLUMN fork_legacy_id BIGINT UNSIGNED NULL,
    ADD CONSTRAINT uk_chat_session_fork_request UNIQUE(fork_owner_user_id,fork_request_id),
    ADD CONSTRAINT uk_chat_session_fork_legacy UNIQUE(fork_legacy_id),
    ADD CONSTRAINT ck_chat_session_fork CHECK (
        (fork_owner_user_id IS NULL AND fork_request_id IS NULL AND fork_source_session_id IS NULL
            AND fork_through_message_id IS NULL AND fork_legacy_id IS NULL)
        OR (fork_owner_user_id IS NOT NULL AND fork_request_id IS NOT NULL
            AND fork_source_session_id IS NOT NULL AND fork_through_message_id IS NOT NULL));
