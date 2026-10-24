-- V57: bounded historical identity snapshot reports. Requires V40/V55/V56.
-- Report metadata only: never remap tasks, infer historical owners, or activate authorization.
CREATE TABLE IF NOT EXISTS detection_identity_reconciliation_report (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 request_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
 actor_user_id BIGINT NOT NULL,
 actor_name VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
 request_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 protocol VARCHAR(48) COLLATE utf8mb4_bin NOT NULL,
 control_revision BIGINT NOT NULL,
 identity_mode VARCHAR(16) COLLATE utf8mb4_bin NOT NULL,
 source_mode VARCHAR(16) COLLATE utf8mb4_bin NOT NULL,
 started_at DATETIME(6) NOT NULL,
 finished_at DATETIME(6) NOT NULL,
 task_count BIGINT NOT NULL,
 role_count BIGINT NOT NULL,
 issue_count BIGINT NOT NULL,
 dataset_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 previous_report_id BIGINT UNSIGNED NULL,
 summary_json JSON NOT NULL,
 UNIQUE KEY uk_identity_reconciliation_request(request_id),
 KEY idx_identity_reconciliation_actor(actor_user_id,id),
 KEY idx_identity_reconciliation_protocol(protocol,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS detection_identity_reconciliation_item (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 report_id BIGINT UNSIGNED NOT NULL,
 task_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
 identity_role VARCHAR(24) COLLATE utf8mb4_bin NOT NULL,
 existing_name VARCHAR(64) COLLATE utf8mb4_bin NULL,
 existing_user_id BIGINT NULL,
 identity_name VARCHAR(64) COLLATE utf8mb4_bin NULL,
 current_username VARCHAR(64) COLLATE utf8mb4_bin NULL,
 current_role VARCHAR(24) COLLATE utf8mb4_bin NULL,
 current_revision CHAR(64) COLLATE utf8mb4_bin NULL,
 source_kind VARCHAR(32) COLLATE utf8mb4_bin NULL,
 source_request_id VARCHAR(128) COLLATE utf8mb4_bin NULL,
 source_sha256 CHAR(64) COLLATE utf8mb4_bin NULL,
 reason_codes JSON NOT NULL,
 item_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 UNIQUE KEY uk_identity_reconciliation_item(report_id,task_id,identity_role),
 KEY idx_identity_reconciliation_page(report_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
