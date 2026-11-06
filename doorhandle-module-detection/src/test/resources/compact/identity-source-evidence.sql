-- Exact original identity CREATE TABLE declarations; no target-derived synthetic source.
CREATE TABLE IF NOT EXISTS detection_identity_control (
 control_id INT PRIMARY KEY,
 mode VARCHAR(16) NOT NULL DEFAULT 'PREVIEW',
 revision BIGINT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS detection_identity_command (
 request_id VARCHAR(128) PRIMARY KEY,
 actor_user_id BIGINT NOT NULL,
 request_sha256 CHAR(64) NOT NULL,
 result_json JSON NOT NULL,
 created_at DATETIME(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS detection_assignment_identity_event (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 task_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
 revision BIGINT NOT NULL,
 actor_user_id BIGINT NOT NULL,
 actor_name VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
 assignee_user_id BIGINT NOT NULL,
 assignee_name VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
 assignee_revision CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 request_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_detection_assignment_revision(task_id,revision),
 UNIQUE KEY uk_detection_assignment_request(actor_user_id,request_id,task_id),
 KEY idx_detection_assignment_actor(actor_user_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
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
CREATE TABLE IF NOT EXISTS detection_identity_binding_event (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 task_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
 identity_role VARCHAR(24) COLLATE utf8mb4_bin NOT NULL,
 revision BIGINT NOT NULL,
 bound_user_id BIGINT NULL,
 bound_identity_name VARCHAR(64) COLLATE utf8mb4_bin NULL,
 target_revision CHAR(64) COLLATE utf8mb4_bin NULL,
 actor_user_id BIGINT NULL,
 actor_name VARCHAR(64) COLLATE utf8mb4_bin NULL,
 source_kind VARCHAR(32) COLLATE utf8mb4_bin NOT NULL,
 request_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
 source_batch_id BIGINT UNSIGNED NULL,
 previous_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 event_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 created_at DATETIME(6) NOT NULL,
 UNIQUE KEY uk_identity_source_revision(task_id,identity_role,revision),
 UNIQUE KEY uk_identity_source_request(task_id,identity_role,request_id),
 KEY idx_identity_source_actor(actor_user_id,id),
 KEY idx_identity_source_batch(source_batch_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS detection_identity_binding (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 task_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
 identity_role VARCHAR(24) COLLATE utf8mb4_bin NOT NULL,
 event_id BIGINT UNSIGNED NOT NULL,
 revision BIGINT NOT NULL,
 event_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 UNIQUE KEY uk_identity_binding_task_role(task_id,identity_role),
 UNIQUE KEY uk_identity_binding_event(event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS detection_identity_source_control (
 control_id INT NOT NULL PRIMARY KEY,
 mode VARCHAR(16) COLLATE utf8mb4_bin NOT NULL DEFAULT 'COLLECTING',
 activation_revision BIGINT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
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
