-- First operation kind in the shared compact operation registry. More typed
-- kinds can add columns and CHECK rules without another physical table.
-- Request receipts intentionally have no cascading FK to mutable sessions.
CREATE TABLE IF NOT EXISTS operation_job (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    namespace VARCHAR(32) COLLATE utf8mb4_bin NOT NULL,
    job_kind VARCHAR(48) COLLATE utf8mb4_bin NOT NULL,
    owner_user_id BIGINT NOT NULL,
    request_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
    request_sha256 CHAR(64) COLLATE utf8mb4_bin NULL,
    status VARCHAR(32) NOT NULL,
    revision BIGINT NOT NULL DEFAULT 0,
    source_session_id VARCHAR(128) COLLATE utf8mb4_bin NULL,
    through_message_id BIGINT NULL,
    result_session_id VARCHAR(128) COLLATE utf8mb4_bin NULL,
    fork_result_key VARCHAR(128) COLLATE utf8mb4_bin GENERATED ALWAYS AS
        (CASE WHEN job_kind='WORKSPACE_FORK' THEN result_session_id ELSE NULL END) VIRTUAL,
    legacy_source VARCHAR(64) COLLATE utf8mb4_bin NULL,
    legacy_id BIGINT UNSIGNED NULL,
    created_at DATETIME(6) NULL,
    UNIQUE KEY uk_operation_job_request(namespace,job_kind,owner_user_id,request_id),
    UNIQUE KEY uk_operation_job_legacy(legacy_source,legacy_id),
    UNIQUE KEY uk_operation_job_fork_child(fork_result_key),
    KEY ix_operation_job_owner(namespace,owner_user_id,job_kind,id),
    CONSTRAINT ck_operation_job_revision CHECK(revision>=0),
    CONSTRAINT ck_operation_job_legacy CHECK (
        (legacy_source IS NULL AND legacy_id IS NULL) OR (legacy_source IS NOT NULL AND legacy_id IS NOT NULL)),
    CONSTRAINT ck_operation_job_fork CHECK (
        job_kind<>'WORKSPACE_FORK' OR (namespace='AGENT_WORKSPACE' AND owner_user_id>0 AND status='COMPLETED'
            AND source_session_id IS NOT NULL AND through_message_id IS NOT NULL AND result_session_id IS NOT NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
