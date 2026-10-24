-- V61: explicit supervisor confirmation of a missing historical name; requires V55/V56.
-- Original business names, reports and audit text are never rewritten or inferred.
CREATE TABLE IF NOT EXISTS detection_identity_missing_name_evidence (
 batch_id BIGINT UNSIGNED NOT NULL,
 task_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
 identity_role VARCHAR(24) COLLATE utf8mb4_bin NOT NULL,
 original_name VARCHAR(64) COLLATE utf8mb4_bin NULL,
 source_snapshot CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 target_user_id BIGINT NOT NULL,
 evidence_reference VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 PRIMARY KEY(batch_id,task_id,identity_role),
 KEY idx_missing_identity_task(task_id,identity_role,batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
