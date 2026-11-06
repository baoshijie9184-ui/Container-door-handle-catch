-- Run once on an isolated V31/V32 source clone with all writers stopped.
-- Records are copied and verified separately; old tables are not dropped here.
ALTER TABLE agent_run
    ADD COLUMN answer_owner_user_id BIGINT NULL,
    ADD COLUMN answer_sha256 CHAR(64) COLLATE utf8mb4_bin NULL,
    ADD COLUMN answer_citations_json JSON NULL,
    ADD COLUMN answer_unresolved_count INT NULL,
    ADD COLUMN answer_recorded_at DATETIME(6) NULL,
    ADD COLUMN answer_legacy_id BIGINT UNSIGNED NULL,
    ADD CONSTRAINT uk_run_answer_legacy UNIQUE(answer_legacy_id),
    ADD CONSTRAINT ck_run_answer_complete CHECK (
        (answer_owner_user_id IS NULL AND answer_sha256 IS NULL AND answer_citations_json IS NULL
            AND answer_unresolved_count IS NULL AND answer_recorded_at IS NULL AND answer_legacy_id IS NULL)
        OR (answer_owner_user_id IS NOT NULL AND answer_owner_user_id=user_id AND answer_sha256 IS NOT NULL
            AND answer_citations_json IS NOT NULL AND answer_unresolved_count IS NOT NULL
            AND answer_unresolved_count>=0 AND answer_recorded_at IS NOT NULL));

ALTER TABLE agent_research_source
    ADD COLUMN purge_owner_user_id BIGINT NULL,
    ADD COLUMN cleared_chars INT NULL,
    ADD COLUMN purged_at DATETIME(6) NULL,
    ADD CONSTRAINT ck_research_purge_complete CHECK (
        (purge_owner_user_id IS NULL AND cleared_chars IS NULL AND purged_at IS NULL)
        OR (purge_owner_user_id IS NOT NULL AND purge_owner_user_id=user_id
            AND cleared_chars IS NOT NULL AND cleared_chars>=0 AND purged_at IS NOT NULL));
