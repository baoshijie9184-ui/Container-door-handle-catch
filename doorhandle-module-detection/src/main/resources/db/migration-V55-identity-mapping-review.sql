-- V55: immutable historical identity mapping receipts. Requires V40.
-- No guessed ownership, account creation, business-name rewrite, backfill or automatic activation.
CREATE TABLE IF NOT EXISTS detection_identity_mapping_batch (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 request_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
 actor_user_id BIGINT NOT NULL,
 actor_name VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
 command_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 revision_before BIGINT NOT NULL,
 revision_after BIGINT NOT NULL,
 applied_count INT NOT NULL,
 result_json JSON NOT NULL,
 created_at DATETIME(6) NOT NULL,
 UNIQUE KEY uk_identity_mapping_request(request_id),
 KEY idx_identity_mapping_actor(actor_user_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS detection_identity_mapping_item (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 batch_id BIGINT UNSIGNED NOT NULL,
 task_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
 identity_role VARCHAR(24) COLLATE utf8mb4_bin NOT NULL,
 source_name VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
 source_snapshot CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 previous_user_id BIGINT NULL,
 previous_identity_name VARCHAR(64) COLLATE utf8mb4_bin NULL,
 target_user_id BIGINT NOT NULL,
 target_username VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
 target_role VARCHAR(24) COLLATE utf8mb4_bin NOT NULL,
 target_revision CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 confirmation_basis VARCHAR(32) COLLATE utf8mb4_bin NOT NULL,
 UNIQUE KEY uk_identity_mapping_item(batch_id,task_id,identity_role),
 KEY idx_identity_mapping_task(task_id,id),
 KEY idx_identity_mapping_target(target_user_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
